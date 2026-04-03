from __future__ import annotations

from decimal import Decimal
import logging
import random
import time

from eth_account import Account
from eth_account.messages import encode_typed_data
from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_env import GrvtEnv
from pysdk.grvt_raw_signing import CHAIN_IDS, get_EIP712_domain_data

from .grvt_auth import GrvtPrivateSession
from .grvt_market import GrvtMarketData
from .grvt_models import (
    FillReport,
    InitialPositionConfig,
    PositionConfig,
    normalize_margin_type,
)


LEVERAGE_SCALE = Decimal("1000000")
POSITION_CONFIG_SIGNATURE_NAME = "SetPositionConfig"
CHAIN_ID_BY_ENV = {env.value: chain_id for env, chain_id in CHAIN_IDS.items()}


class GrvtTradingGateway:
    _ORDER_ACK_FETCH_ATTEMPTS = 3
    _ORDER_ACK_FETCH_DELAY_SECONDS = 1

    def __init__(
        self,
        *,
        client: GrvtCcxt,
        env: GrvtEnv,
        private_key: str,
        trading_account_id: str,
        trade_data_endpoint: str,
        auth: GrvtPrivateSession,
        market: GrvtMarketData,
        logger: logging.Logger,
    ) -> None:
        self._client = client
        self._env = env
        self._private_key = private_key
        self._trading_account_id = trading_account_id
        self._trade_data_endpoint = trade_data_endpoint
        self._auth = auth
        self._market = market
        self._logger = logger

    def _trade_path(self, suffix: str) -> str:
        return f"{self._trade_data_endpoint}/{suffix.lstrip('/')}"

    def _initial_position_config_from_payload(self, payload: dict) -> InitialPositionConfig:
        return InitialPositionConfig(
            symbol=str(payload.get("instrument", "")),
            leverage=(
                Decimal(str(payload["leverage"]))
                if payload.get("leverage") not in (None, "")
                else None
            ),
            min_leverage=(
                Decimal(str(payload["min_leverage"]))
                if payload.get("min_leverage") not in (None, "")
                else None
            ),
            max_leverage=(
                Decimal(str(payload["max_leverage"]))
                if payload.get("max_leverage") not in (None, "")
                else None
            ),
            margin_type=normalize_margin_type(payload.get("margin_type")),
            raw=payload,
        )

    def get_initial_position_details(self, symbol: str) -> InitialPositionConfig:
        response = self._auth.auth_and_post(
            self._trade_path("full/v1/get_all_initial_leverage"),
            {"sub_account_id": self._trading_account_id},
        )
        for item in response.get("results", response.get("result", {}).get("results", [])):
            if item.get("instrument") == symbol:
                return self._initial_position_config_from_payload(item)
        return InitialPositionConfig(symbol=symbol)

    def get_initial_position_config(self, symbol: str) -> PositionConfig:
        details = self.get_initial_position_details(symbol)
        return PositionConfig(leverage=details.leverage, margin_type=details.margin_type)

    def get_initial_leverage(self, symbol: str) -> Decimal | None:
        return self.get_initial_position_config(symbol).leverage

    def get_effective_position_config(self, symbol: str) -> PositionConfig:
        position_config = self._market.position_config_from_payload(self._market.get_position(symbol))
        if position_config.leverage is not None or position_config.margin_type is not None:
            return position_config
        initial_config = self.get_initial_position_config(symbol)
        if initial_config.leverage is not None or initial_config.margin_type is not None:
            return initial_config
        return PositionConfig(margin_type=self._market.get_account_margin_type())

    def set_initial_leverage(self, symbol: str, leverage: Decimal) -> None:
        response = self._auth.auth_and_post(
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
        response = self._auth.auth_and_post(
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

        current_position = self._market.get_position(symbol)
        initial_config = self.get_initial_position_config(symbol)
        current_margin_type = (
            normalize_margin_type((current_position or {}).get("margin_type"))
            or initial_config.margin_type
            or self._market.get_account_margin_type()
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

        if desired_leverage is None:
            raise ValueError(
                f"Cannot set initial leverage for {symbol} because desired leverage is unknown"
            )
        self._logger.info("Setting GRVT initial leverage for %s leverage=%s", symbol, leverage)
        self.set_initial_leverage(symbol, desired_leverage)
        return [f"leverage={desired_leverage}"]

    def _extract_order_id(self, response: object) -> str | None:
        if not isinstance(response, dict):
            return None
        result = response.get("result", response)
        if not isinstance(result, dict):
            return None
        order_id = result.get("order_id") or result.get("id")
        if order_id in (None, ""):
            return None
        return str(order_id)

    def _matching_client_order_id(self, payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and metadata.get("client_order_id") not in (None, ""):
            return str(metadata["client_order_id"])
        for key in ("clientOrderId", "client_order_id"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    def _fetch_order_submission_ack(self, *, symbol: str, client_order_id: str) -> dict | None:
        for attempt in range(1, self._ORDER_ACK_FETCH_ATTEMPTS + 1):
            try:
                response = self.fetch_order(client_order_id=client_order_id)
            except Exception as exc:
                self._logger.warning(
                    "GRVT order ack lookup failed after create_order returned no order id. "
                    "attempt=%s/%s client_order_id=%s error=%s",
                    attempt,
                    self._ORDER_ACK_FETCH_ATTEMPTS,
                    client_order_id,
                    exc,
                )
            else:
                if self._extract_order_id(response) is not None:
                    return response
            try:
                open_orders = self.fetch_open_orders(symbol=symbol)
            except Exception as exc:
                self._logger.warning(
                    "GRVT open-order ack lookup failed after create_order returned no order id. "
                    "attempt=%s/%s client_order_id=%s error=%s",
                    attempt,
                    self._ORDER_ACK_FETCH_ATTEMPTS,
                    client_order_id,
                    exc,
                )
            else:
                for payload in open_orders:
                    if self._matching_client_order_id(payload) == client_order_id:
                        return payload
            if attempt < self._ORDER_ACK_FETCH_ATTEMPTS:
                time.sleep(self._ORDER_ACK_FETCH_DELAY_SECONDS)
        return None

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
        self._auth.ensure_private_auth()
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
        if self._extract_order_id(response) is not None:
            return response
        fallback_response = self._fetch_order_submission_ack(
            symbol=symbol,
            client_order_id=client_order_id,
        )
        if fallback_response is not None:
            self._logger.warning(
                "GRVT create_order returned no order id, but fetch_order confirmed submission. "
                "client_order_id=%s",
                client_order_id,
            )
            return fallback_response
        return response

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> bool:
        self._auth.ensure_private_auth()
        params = {"client_order_id": client_order_id} if client_order_id is not None else {}
        return self._client.cancel_order(id=order_id, symbol=symbol, params=params)

    def fetch_order(self, *, order_id: str | None = None, client_order_id: str | None = None) -> dict:
        if order_id is None and client_order_id is None:
            raise ValueError("fetch_order requires order_id or client_order_id")
        params = {"client_order_id": client_order_id} if client_order_id is not None else {}
        return self._client.fetch_order(id=order_id, params=params)

    def fetch_open_orders(self, *, symbol: str) -> list[dict]:
        self._auth.ensure_private_auth()
        response = self._client.fetch_open_orders(symbol=symbol)
        if isinstance(response, dict):
            result = response.get("result")
            if isinstance(result, list):
                return result
        if isinstance(response, list):
            return response
        return []

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
                order_id=(
                    last_report.order_id
                    if last_report is not None and last_report.order_id
                    else None
                ),
                client_order_id=client_order_id,
            )
            return None
        if last_report is not None:
            raise ValueError(
                f"Timed out waiting for fill: status={last_report.status} "
                f"traded_size={last_report.traded_size} avg_fill_price={last_report.avg_fill_price}"
            )
        raise ValueError("Timed out waiting for GRVT order status")
