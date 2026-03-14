from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import logging
import random
import time

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_env import (
    GrvtEndpointType,
    GrvtEnv,
    get_grvt_endpoint,
    get_grvt_endpoint_domains,
)
from pysdk.grvt_raw_signing import CHAIN_IDS, get_EIP712_domain_data

from .config import GrvtCredentials


PRICE_SCALE = Decimal("1000000000")
LEVERAGE_SCALE = Decimal("1000000")
POSITION_CONFIG_SIGNATURE_NAME = "SetPositionConfig"
CHAIN_ID_BY_ENV = {env.value: chain_id for env, chain_id in CHAIN_IDS.items()}
MARGIN_TYPE_ALIASES = {
    "cross": "CROSS",
    "cross_margin": "CROSS",
    "simple_cross_margin": "CROSS",
    "portfolio_cross_margin": "CROSS",
    "isolated": "ISOLATED",
    "isolated_margin": "ISOLATED",
}


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    last: Decimal


@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    tick_size: Decimal
    min_size: Decimal
    min_notional: Decimal
    base_decimals: int


@dataclass(frozen=True)
class FillReport:
    order_id: str
    client_order_id: str
    status: str
    traded_size: Decimal
    avg_fill_price: Decimal
    raw: dict


@dataclass(frozen=True)
class PositionConfig:
    leverage: Decimal | None = None
    margin_type: str | None = None


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    side: str
    size: Decimal
    average_entry_price: Decimal
    leverage: Decimal | None = None
    margin_type: str | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class AccountFill:
    event_time: int
    symbol: str
    side: str
    size: Decimal
    price: Decimal
    order_id: str | None = None
    client_order_id: str | None = None
    raw: dict | None = None


class TransientExchangeError(RuntimeError):
    pass


def parse_grvt_decimal(value: str | int | float | Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    text = str(value)
    parsed = Decimal(text)
    if "." in text:
        return parsed
    if abs(parsed) >= PRICE_SCALE:
        return parsed / PRICE_SCALE
    return parsed


def normalize_margin_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return MARGIN_TYPE_ALIASES.get(normalized.lower(), normalized.upper())


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

        self._logger = logger
        self._env = env
        self._api_key = credentials.api_key
        self._private_key = credentials.private_key
        self._trading_account_id = credentials.trading_account_id
        self._private_auth_retry_attempts = max(private_auth_retry_attempts, 1)
        self._private_auth_retry_backoff_seconds = max(private_auth_retry_backoff_seconds, 0)
        endpoint_domains = get_grvt_endpoint_domains(env.value)
        self._trade_data_endpoint = endpoint_domains[GrvtEndpointType.TRADE_DATA]
        self._client = GrvtCcxt(
            env=env,
            logger=logger,
            parameters={
                "api_key": credentials.api_key,
                "private_key": credentials.private_key,
                "trading_account_id": credentials.trading_account_id,
            },
        )

    def _trade_path(self, suffix: str) -> str:
        return f"{self._trade_data_endpoint}/{suffix.lstrip('/')}"

    def _auth_and_post(self, path: str, payload: dict) -> dict:
        self.ensure_private_auth()
        try:
            return self._client._auth_and_post(path, payload)
        except Exception as exc:
            response = getattr(exc, "response", None)
            if response is not None and getattr(response, "status_code", None) == 401:
                self._logger.warning(
                    "GRVT private POST returned 401, refreshing auth and retrying once. path=%s",
                    path,
                )
                self.ensure_private_auth()
                return self._client._auth_and_post(path, payload)
            if self._is_transient_request_error(exc):
                raise TransientExchangeError(f"GRVT request failed for {path}: {exc}") from exc
            raise

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

    def _is_retryable_auth_http_status(self, status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _is_transient_request_error(self, exc: Exception) -> bool:
        if isinstance(exc, requests.exceptions.SSLError):
            return True
        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        return False

    def ensure_private_auth(self) -> None:
        auth_url = get_grvt_endpoint(self._env, "AUTH")
        last_error: Exception | None = None
        for attempt in range(1, self._private_auth_retry_attempts + 1):
            try:
                response = requests.post(
                    auth_url,
                    json={"api_key": self._api_key},
                    timeout=10,
                )
                if not response.ok:
                    message = (
                        f"GRVT auth failed with HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    )
                    if (
                        self._is_retryable_auth_http_status(response.status_code)
                        and attempt < self._private_auth_retry_attempts
                    ):
                        self._logger.warning(
                            "Retrying GRVT private auth after HTTP %s attempt=%s/%s",
                            response.status_code,
                            attempt,
                            self._private_auth_retry_attempts,
                        )
                        time.sleep(self._private_auth_retry_backoff_seconds * attempt)
                        continue
                    raise ValueError(message)
                if "gravity" not in response.headers.get("Set-Cookie", ""):
                    raise ValueError(
                        f"GRVT auth did not return a session cookie: {response.text[:200]}"
                    )
                return
            except Exception as exc:
                last_error = exc
                if (
                    self._is_transient_request_error(exc)
                    and attempt < self._private_auth_retry_attempts
                ):
                    self._logger.warning(
                        "Retrying GRVT private auth after transient error attempt=%s/%s error=%s",
                        attempt,
                        self._private_auth_retry_attempts,
                        exc,
                    )
                    time.sleep(self._private_auth_retry_backoff_seconds * attempt)
                    continue
                if self._is_transient_request_error(exc):
                    raise TransientExchangeError(
                        f"GRVT private auth failed after {attempt} attempts: {exc}"
                    ) from exc
                raise
        if last_error is not None:
            raise TransientExchangeError(
                f"GRVT private auth failed after {self._private_auth_retry_attempts} attempts: "
                f"{last_error}"
            ) from last_error

    def get_account_margin_type(self) -> str | None:
        try:
            summary = self._client.get_account_summary("sub-account")
        except Exception as exc:
            if self._is_transient_request_error(exc):
                raise TransientExchangeError(f"GRVT account summary failed: {exc}") from exc
            raise
        return normalize_margin_type(summary.get("margin_type"))

    def get_position(self, symbol: str) -> dict | None:
        try:
            positions = self._client.fetch_positions([symbol])
        except Exception as exc:
            if self._is_transient_request_error(exc):
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
        config = self._position_config_from_payload(position)
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
        self.ensure_private_auth()
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
                if self._is_transient_request_error(exc):
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

    def _position_config_from_payload(self, payload: dict | None) -> PositionConfig:
        if payload is None:
            return PositionConfig()
        leverage = (
            Decimal(str(payload["leverage"]))
            if payload.get("leverage") not in (None, "")
            else None
        )
        margin_type = normalize_margin_type(payload.get("margin_type"))
        return PositionConfig(leverage=leverage, margin_type=margin_type)

    def get_position_size(self, symbol: str) -> Decimal:
        position = self.get_position(symbol)
        if position is None:
            return Decimal("0")
        return Decimal(str(position.get("size", "0")))

    def get_position_margin_type(self, symbol: str) -> str | None:
        return self._position_config_from_payload(self.get_position(symbol)).margin_type

    def get_position_leverage(self, symbol: str) -> Decimal | None:
        return self._position_config_from_payload(self.get_position(symbol)).leverage

    def get_initial_position_config(self, symbol: str) -> PositionConfig:
        response = self._auth_and_post(
            self._trade_path("full/v1/get_all_initial_leverage"),
            {"sub_account_id": self._trading_account_id},
        )
        for item in response.get("results", response.get("result", {}).get("results", [])):
            if item.get("instrument") == symbol:
                return self._position_config_from_payload(item)
        return PositionConfig()

    def get_initial_leverage(self, symbol: str) -> Decimal | None:
        return self.get_initial_position_config(symbol).leverage

    def get_effective_position_config(self, symbol: str) -> PositionConfig:
        position_config = self._position_config_from_payload(self.get_position(symbol))
        if position_config.leverage is not None or position_config.margin_type is not None:
            return position_config
        initial_config = self.get_initial_position_config(symbol)
        if initial_config.leverage is not None or initial_config.margin_type is not None:
            return initial_config
        return PositionConfig(margin_type=self.get_account_margin_type())

    def set_initial_leverage(self, symbol: str, leverage: Decimal) -> None:
        response = self._auth_and_post(
            self._trade_path("full/v1/set_initial_leverage"),
            {
                "sub_account_id": self._trading_account_id,
                "instrument": symbol,
                "leverage": str(leverage),
            },
        )
        success = response.get("success", response.get("result", {}).get("success"))
        if success is not True:
            raise ValueError(f"GRVT set_initial_leverage failed: {response}")

    def _build_position_config_signature(
        self,
        *,
        symbol: str,
        margin_type: str,
        leverage: Decimal,
    ) -> dict:
        expiration_ns = int((time.time() + 86400) * 1_000_000_000)
        nonce = random.randint(1, 2**32 - 1)
        signer = Account.from_key(self._private_key)
        chain_id = CHAIN_ID_BY_ENV[self._env.value]
        typed_data = {
            POSITION_CONFIG_SIGNATURE_NAME: [
                {"name": "subAccountID", "type": "uint64"},
                {"name": "instrument", "type": "string"},
                {"name": "marginType", "type": "string"},
                {"name": "leverageE6", "type": "uint64"},
                {"name": "nonce", "type": "uint32"},
                {"name": "expiration", "type": "int64"},
            ]
        }
        payload = {
            "subAccountID": int(self._trading_account_id),
            "instrument": symbol,
            "marginType": margin_type,
            "leverageE6": int(leverage * LEVERAGE_SCALE),
            "nonce": nonce,
            "expiration": expiration_ns,
        }
        message = encode_typed_data(
            get_EIP712_domain_data(self._env, chain_id),
            typed_data,
            payload,
        )
        signed = Account.sign_message(message, self._private_key)
        return {
            "signer": signer.address.lower(),
            "r": hex(signed.r),
            "s": hex(signed.s),
            "v": signed.v,
            "expiration": str(expiration_ns),
            "nonce": nonce,
            "chain_id": chain_id,
        }

    def set_position_config(self, symbol: str, margin_type: str, leverage: Decimal) -> None:
        normalized_margin_type = normalize_margin_type(margin_type)
        if normalized_margin_type is None:
            raise ValueError("margin_type must not be empty")
        response = self._auth_and_post(
            self._trade_path("full/v1/set_position_config"),
            {
                "sub_account_id": self._trading_account_id,
                "instrument": symbol,
                "margin_type": normalized_margin_type,
                "leverage": str(leverage),
                "signature": self._build_position_config_signature(
                    symbol=symbol,
                    margin_type=normalized_margin_type,
                    leverage=leverage,
                ),
            },
        )
        success = response.get("success", response.get("result", {}).get("success"))
        if success is not True:
            raise ValueError(f"GRVT set_position_config failed: {response}")

    def ensure_position_config(
        self,
        *,
        symbol: str,
        leverage: Decimal | None,
        margin_type: str | None,
        dry_run: bool,
    ) -> list[str]:
        desired_margin_type = normalize_margin_type(margin_type)
        desired_leverage = leverage
        if desired_margin_type is None and desired_leverage is None:
            return []

        current_position = self.get_position(symbol)
        initial_config = self.get_initial_position_config(symbol)
        current_margin_type = (
            normalize_margin_type((current_position or {}).get("margin_type"))
            or initial_config.margin_type
            or self.get_account_margin_type()
        )
        current_leverage = (
            Decimal(str(current_position["leverage"]))
            if current_position and current_position.get("leverage") not in (None, "")
            else None
        )
        if current_leverage is None:
            current_leverage = initial_config.leverage

        if desired_margin_type is not None and current_margin_type == desired_margin_type:
            desired_margin_type = None
        if desired_leverage is not None and current_leverage == desired_leverage:
            desired_leverage = None
        if desired_margin_type is None and desired_leverage is None:
            return []

        open_size = abs(Decimal(str((current_position or {}).get("size", "0"))))
        if desired_margin_type is not None and open_size > 0:
            raise ValueError(
                f"Cannot change margin_type for {symbol} while an open position exists. "
                f"current_margin_type={current_margin_type} desired_margin_type={desired_margin_type}"
            )

        if dry_run:
            self._logger.info(
                "Dry run: position config differs for %s current_margin_type=%s desired_margin_type=%s "
                "current_leverage=%s desired_leverage=%s",
                symbol,
                current_margin_type,
                normalize_margin_type(margin_type),
                current_leverage,
                leverage,
            )
            return []

        if desired_margin_type is not None:
            effective_leverage = desired_leverage or current_leverage
            if effective_leverage is None:
                raise ValueError(
                    f"Cannot set margin_type for {symbol} because current leverage is unknown"
                )
            self._logger.info(
                "Setting GRVT position config for %s margin_type=%s leverage=%s",
                symbol,
                desired_margin_type,
                effective_leverage,
            )
            self.set_position_config(symbol, desired_margin_type, effective_leverage)
            return [
                f"margin_type={desired_margin_type}",
                f"leverage={effective_leverage}",
            ]

        self._logger.info("Setting GRVT initial leverage for %s leverage=%s", symbol, leverage)
        self.set_initial_leverage(symbol, desired_leverage)
        return [f"leverage={desired_leverage}"]

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
        self.ensure_private_auth()
        params = {
            "client_order_id": client_order_id,
            "reduce_only": reduce_only,
        }
        response = self._client.create_order(
            symbol=symbol,
            order_type=order_type,
            side=side,
            amount=str(amount),
            price=str(price) if price is not None else None,
            params=params,
        )
        self._logger.info("order_response=%s", response)
        return response

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> bool:
        self.ensure_private_auth()
        params = {"client_order_id": client_order_id} if client_order_id is not None else {}
        return self._client.cancel_order(id=order_id, symbol=symbol, params=params)

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None) -> dict:
        if order_id is None and client_order_id is None:
            raise ValueError("fetch_order requires order_id or client_order_id")
        params = {"client_order_id": client_order_id} if client_order_id is not None else {}
        return self._client.fetch_order(id=order_id, params=params)

    def parse_fill_report(self, response: dict) -> FillReport | None:
        result = response.get("result", response)
        if not isinstance(result, dict) or not result:
            return None
        state = result.get("state", {}) or {}
        traded = state.get("traded_size", ["0"])
        avg_fill = state.get("avg_fill_price", ["0"])
        traded_size = Decimal(str(traded[0] if traded else "0"))
        avg_fill_price = Decimal(str(avg_fill[0] if avg_fill else "0"))
        return FillReport(
            order_id=str(result.get("order_id", "")),
            client_order_id=str(result.get("metadata", {}).get("client_order_id", "")),
            status=str(state.get("status", "UNKNOWN")),
            traded_size=traded_size,
            avg_fill_price=avg_fill_price,
            raw=result,
        )

    def wait_for_fill(
        self,
        *,
        symbol: str,
        order_type: str,
        client_order_id: str,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> FillReport | None:
        deadline = time.time() + timeout_seconds
        last_report: FillReport | None = None
        while time.time() < deadline:
            response = self.fetch_order(client_order_id=client_order_id)
            report = self.parse_fill_report(response)
            if report is not None:
                last_report = report
                if report.traded_size > 0 and report.avg_fill_price > 0:
                    return report
                reject_reason = (
                    report.raw.get("state", {}).get("reject_reason", "UNSPECIFIED")
                    if isinstance(report.raw, dict)
                    else "UNSPECIFIED"
                )
                if report.status in {"CANCELLED", "REJECTED"} or reject_reason != "UNSPECIFIED":
                    raise ValueError(
                        f"GRVT order was not fillable: status={report.status} reject_reason={reject_reason}"
                    )
            time.sleep(poll_seconds)
        if order_type == "limit":
            self._logger.warning(
                "Limit order timed out waiting for fill. client_order_id=%s last_status=%s",
                client_order_id,
                last_report.status if last_report is not None else "UNKNOWN",
            )
            self.cancel_order(
                symbol=symbol,
                order_id=(last_report.order_id if last_report is not None and last_report.order_id else None),
                client_order_id=client_order_id,
            )
            return None
        if last_report is not None:
            raise ValueError(
                f"Timed out waiting for fill: status={last_report.status} "
                f"traded_size={last_report.traded_size} avg_fill_price={last_report.avg_fill_price}"
            )
        raise ValueError("Timed out waiting for GRVT order status")
