from __future__ import annotations

from decimal import Decimal
import logging

from pysdk.grvt_ccxt import GrvtCcxt

from .grvt_auth import GrvtPrivateSession
from .grvt_models import (
    AccountFill,
    InstrumentMeta,
    MarketSnapshot,
    PositionConfig,
    PositionSnapshot,
    TransientExchangeError,
    normalize_margin_type,
    parse_grvt_decimal,
)


class GrvtMarketData:
    def __init__(
        self,
        *,
        client: GrvtCcxt,
        auth: GrvtPrivateSession,
        logger: logging.Logger,
    ) -> None:
        self._client = client
        self._auth = auth
        self._logger = logger

    def get_instrument(self, symbol: str) -> InstrumentMeta:
        market = self._client.fetch_market(symbol)
        return InstrumentMeta(
            symbol=symbol,
            tick_size=Decimal(str(market["tick_size"])),
            min_size=Decimal(str(market["min_size"])),
            min_notional=Decimal(str(market.get("min_notional", "0"))),
            base_decimals=int(market["base_decimals"]),
        )

    def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        ticker = self._client.fetch_mini_ticker(symbol)
        bid = parse_grvt_decimal(ticker["best_bid_price"])
        ask = parse_grvt_decimal(ticker["best_ask_price"])
        mid = parse_grvt_decimal(ticker["mid_price"])
        last = parse_grvt_decimal(ticker["last_price"])
        return MarketSnapshot(symbol=symbol, bid=bid, ask=ask, mid=mid, last=last)

    def position_config_from_payload(self, payload: dict | None) -> PositionConfig:
        if payload is None:
            return PositionConfig()
        leverage = (
            Decimal(str(payload["leverage"]))
            if payload.get("leverage") not in (None, "")
            else None
        )
        margin_type = normalize_margin_type(payload.get("margin_type"))
        return PositionConfig(leverage=leverage, margin_type=margin_type)

    def get_account_margin_type(self) -> str | None:
        try:
            summary = self._client.get_account_summary("sub-account")
        except Exception as exc:
            if self._auth.is_transient_request_error(exc):
                raise TransientExchangeError(f"GRVT account summary failed: {exc}") from exc
            raise
        return normalize_margin_type(summary.get("margin_type"))

    def get_position(self, symbol: str) -> dict | None:
        try:
            positions = self._client.fetch_positions([symbol])
        except Exception as exc:
            if self._auth.is_transient_request_error(exc):
                raise TransientExchangeError(f"GRVT fetch_positions failed for {symbol}: {exc}") from exc
            raise
        for position in positions:
            if position.get("instrument") == symbol:
                return position
        return None

    def get_open_position(self, symbol: str) -> PositionSnapshot | None:
        position = self.get_position(symbol)
        if position is None:
            return None
        signed_size = Decimal(str(position.get("size", "0")))
        if signed_size == 0:
            return None
        side_value = str(position.get("side", "")).strip().lower()
        if side_value not in {"buy", "sell"}:
            side_value = "buy" if signed_size > 0 else "sell"
        average_entry_price = Decimal(
            str(position.get("entry_price", position.get("average_entry_price", "0")))
        )
        if average_entry_price <= 0:
            raise ValueError(
                f"GRVT returned an open position without a valid entry price for {symbol}: {position}"
            )
        config = self.position_config_from_payload(position)
        return PositionSnapshot(
            symbol=symbol,
            side=side_value,
            size=abs(signed_size),
            average_entry_price=average_entry_price,
            leverage=config.leverage,
            margin_type=config.margin_type,
            raw=position,
        )

    def _parse_fill(self, payload: dict) -> AccountFill:
        side = "buy" if bool(payload.get("is_buyer")) else "sell"
        return AccountFill(
            event_time=int(payload.get("event_time", "0")),
            symbol=str(payload.get("instrument", "")),
            side=side,
            size=Decimal(str(payload.get("size", "0"))),
            price=Decimal(str(payload.get("price", "0"))),
            order_id=str(payload["order_id"]) if payload.get("order_id") else None,
            client_order_id=(
                str(payload["client_order_id"]) if payload.get("client_order_id") else None
            ),
            raw=payload,
        )

    def get_recent_fills(self, symbol: str, *, limit: int = 100) -> list[AccountFill]:
        self._auth.ensure_private_auth()
        fills: list[AccountFill] = []
        cursor: str | None = None
        while len(fills) < limit:
            params = {"cursor": cursor} if cursor else {}
            try:
                response = self._client.fetch_my_trades(
                    symbol=symbol,
                    limit=min(50, limit - len(fills)),
                    params=params,
                )
            except Exception as exc:
                if self._auth.is_transient_request_error(exc):
                    raise TransientExchangeError(
                        f"GRVT fetch_my_trades failed for {symbol}: {exc}"
                    ) from exc
                raise
            page = [self._parse_fill(item) for item in response.get("result", [])]
            if not page:
                break
            fills.extend(page)
            cursor = response.get("next")
            if not cursor:
                break
        return fills[:limit]
