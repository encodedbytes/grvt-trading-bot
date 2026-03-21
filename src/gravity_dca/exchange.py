from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import logging

from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_env import GrvtEndpointType, GrvtEnv, get_grvt_endpoint_domains

from .config import GrvtCredentials
from .grvt_auth import GrvtPrivateSession
from .grvt_market import GrvtMarketData
from .grvt_models import (
    AccountFill,
    Candle,
    FillReport,
    InitialPositionConfig,
    InstrumentMeta,
    MarketSnapshot,
    PositionConfig,
    PositionSnapshot,
    TransientExchangeError,
    normalize_margin_type,
    parse_grvt_decimal,
)
from .grvt_trading import GrvtTradingGateway


class GrvtExchange:
    def __init__(
        self,
        credentials: GrvtCredentials,
        logger: logging.Logger,
        *,
        private_auth_retry_attempts: int = 3,
        private_auth_retry_backoff_seconds: int = 2,
    ) -> None:
        try:
            env = GrvtEnv(credentials.environment)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported GRVT environment: {credentials.environment!r}"
            ) from exc

        endpoint_domains = get_grvt_endpoint_domains(env.value)
        trade_data_endpoint = endpoint_domains[GrvtEndpointType.TRADE_DATA]
        client = GrvtCcxt(
            env=env,
            logger=logger,
            parameters={
                "api_key": credentials.api_key,
                "private_key": credentials.private_key,
                "trading_account_id": credentials.trading_account_id,
            },
        )

        self._logger = logger
        self._client = client
        self._auth = GrvtPrivateSession(
            env=env,
            api_key=credentials.api_key,
            client=client,
            logger=logger,
            retry_attempts=private_auth_retry_attempts,
            retry_backoff_seconds=private_auth_retry_backoff_seconds,
        )
        self._market = GrvtMarketData(client=client, auth=self._auth, logger=logger)
        self._trading = GrvtTradingGateway(
            client=client,
            env=env,
            private_key=credentials.private_key,
            trading_account_id=credentials.trading_account_id,
            trade_data_endpoint=trade_data_endpoint,
            auth=self._auth,
            market=self._market,
            logger=logger,
        )

    def round_amount(self, amount: Decimal, base_decimals: int) -> Decimal:
        quantum = Decimal("1").scaleb(-base_decimals)
        return amount.quantize(quantum, rounding=ROUND_DOWN)

    def align_amount_to_market(self, amount: Decimal, instrument: InstrumentMeta) -> Decimal:
        rounded = self.round_amount(amount, instrument.base_decimals)
        if instrument.min_size <= 0:
            return rounded
        steps = (rounded / instrument.min_size).to_integral_value(rounding=ROUND_DOWN)
        return steps * instrument.min_size

    def round_price(self, price: Decimal, tick_size: Decimal) -> Decimal:
        steps = (price / tick_size).to_integral_value(rounding=ROUND_DOWN)
        return steps * tick_size

    def ensure_private_auth(self) -> None:
        self._auth.ensure_private_auth()

    def get_instrument(self, symbol: str) -> InstrumentMeta:
        return self._market.get_instrument(symbol)

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        return self._market.get_market_snapshot(symbol)

    def get_candles(
        self,
        symbol: str,
        *,
        timeframe: str,
        since: int = 0,
        limit: int = 200,
        candle_type: str = "TRADE",
    ) -> list[Candle]:
        return self._market.get_candles(
            symbol,
            timeframe=timeframe,
            since=since,
            limit=limit,
            candle_type=candle_type,
        )

    def get_account_margin_type(self) -> str | None:
        return self._market.get_account_margin_type()

    def get_position(self, symbol: str) -> dict | None:
        return self._market.get_position(symbol)

    def get_open_position(self, symbol: str) -> PositionSnapshot | None:
        return self._market.get_open_position(symbol)

    def get_recent_fills(self, symbol: str, *, limit: int = 100) -> list[AccountFill]:
        return self._market.get_recent_fills(symbol, limit=limit)

    def get_position_size(self, symbol: str) -> Decimal:
        position = self.get_position(symbol)
        if position is None:
            return Decimal("0")
        return Decimal(str(position.get("size", "0")))

    def get_position_margin_type(self, symbol: str) -> str | None:
        return self._market.position_config_from_payload(self.get_position(symbol)).margin_type

    def get_position_leverage(self, symbol: str) -> Decimal | None:
        return self._market.position_config_from_payload(self.get_position(symbol)).leverage

    def get_initial_position_config(self, symbol: str) -> PositionConfig:
        return self._trading.get_initial_position_config(symbol)

    def get_initial_position_details(self, symbol: str) -> InitialPositionConfig:
        return self._trading.get_initial_position_details(symbol)

    def get_initial_leverage(self, symbol: str) -> Decimal | None:
        return self._trading.get_initial_leverage(symbol)

    def get_effective_position_config(self, symbol: str) -> PositionConfig:
        return self._trading.get_effective_position_config(symbol)

    def set_initial_leverage(self, symbol: str, leverage: Decimal) -> None:
        self._trading.set_initial_leverage(symbol, leverage)

    def set_position_config(self, symbol: str, margin_type: str, leverage: Decimal) -> None:
        self._trading.set_position_config(symbol, margin_type, leverage)

    def ensure_position_config(
        self,
        *,
        symbol: str,
        leverage: Decimal | None,
        margin_type: str | None,
        dry_run: bool,
    ) -> list[str]:
        return self._trading.ensure_position_config(
            symbol=symbol,
            leverage=leverage,
            margin_type=margin_type,
            dry_run=dry_run,
        )

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        amount: Decimal,
        price: Decimal | None,
        client_order_id: str,
        reduce_only: bool = False,
    ) -> dict:
        return self._trading.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            client_order_id=client_order_id,
            reduce_only=reduce_only,
        )

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> bool:
        return self._trading.cancel_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None) -> dict:
        return self._trading.fetch_order(order_id=order_id, client_order_id=client_order_id)

    def parse_fill_report(self, response: dict) -> FillReport | None:
        return self._trading.parse_fill_report(response)

    def wait_for_fill(
        self,
        *,
        symbol: str,
        order_type: str,
        client_order_id: str,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> FillReport | None:
        return self._trading.wait_for_fill(
            symbol=symbol,
            order_type=order_type,
            client_order_id=client_order_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )


__all__ = [
    "AccountFill",
    "Candle",
    "FillReport",
    "GrvtExchange",
    "InitialPositionConfig",
    "InstrumentMeta",
    "MarketSnapshot",
    "PositionConfig",
    "PositionSnapshot",
    "TransientExchangeError",
    "normalize_margin_type",
    "parse_grvt_decimal",
]
