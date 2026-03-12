from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import logging
import time

import requests
from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_env import GrvtEnv, get_grvt_endpoint

from .config import GrvtCredentials


PRICE_SCALE = Decimal("1000000000")


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


class GrvtExchange:
    def __init__(self, credentials: GrvtCredentials, logger: logging.Logger) -> None:
        try:
            env = GrvtEnv(credentials.environment)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported GRVT environment: {credentials.environment!r}"
            ) from exc

        self._logger = logger
        self._env = env
        self._api_key = credentials.api_key
        self._client = GrvtCcxt(
            env=env,
            logger=logger,
            parameters={
                "api_key": credentials.api_key,
                "private_key": credentials.private_key,
                "trading_account_id": credentials.trading_account_id,
            },
        )

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

    def ensure_private_auth(self) -> None:
        response = requests.post(
            get_grvt_endpoint(self._env, "AUTH"),
            json={"api_key": self._api_key},
            timeout=10,
        )
        if not response.ok:
            raise ValueError(
                f"GRVT auth failed with HTTP {response.status_code}: {response.text[:200]}"
            )
        if "gravity" not in response.headers.get("Set-Cookie", ""):
            raise ValueError(f"GRVT auth did not return a session cookie: {response.text[:200]}")

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
        client_order_id: str,
        timeout_seconds: int,
        poll_seconds: int,
    ) -> FillReport:
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
        if last_report is not None:
            raise ValueError(
                f"Timed out waiting for fill: status={last_report.status} "
                f"traded_size={last_report.traded_size} avg_fill_price={last_report.avg_fill_price}"
            )
        raise ValueError("Timed out waiting for GRVT order status")
