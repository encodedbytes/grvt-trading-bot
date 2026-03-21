from __future__ import annotations

import logging
from types import SimpleNamespace
from decimal import Decimal

import requests

from gravity_dca.grvt_market import GrvtMarketData
from gravity_dca.grvt_auth import GrvtPrivateSession
from gravity_dca.grvt_models import TransientExchangeError


def auth_session(attempts: int) -> GrvtPrivateSession:
    client = SimpleNamespace(
        _session=SimpleNamespace(cookies={}, headers={}),
        _cookie=None,
    )
    return GrvtPrivateSession(
        env=object(),
        api_key="key",
        client=client,
        logger=logging.getLogger("gravity_dca"),
        retry_attempts=attempts,
        retry_backoff_seconds=0,
    )


def test_ensure_private_auth_retries_transient_ssl_errors(monkeypatch) -> None:
    session = auth_session(3)
    calls = {"count": 0}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.SSLError("unexpected eof")
        return SimpleNamespace(
            ok=True,
            headers={"Set-Cookie": "gravity=session; expires=Wed, 18 Mar 2026 12:00:00 GMT"},
            text="",
        )

    monkeypatch.setattr("gravity_dca.grvt_auth.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.grvt_auth.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    session.ensure_private_auth()

    assert calls["count"] == 3
    assert session._client._cookie is not None
    assert session._client._session.cookies["gravity"] == "session"


def test_ensure_private_auth_raises_transient_exchange_error_after_retries(monkeypatch) -> None:
    session = auth_session(2)

    def fake_post(*args, **kwargs):
        raise requests.exceptions.SSLError("unexpected eof")

    monkeypatch.setattr("gravity_dca.grvt_auth.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.grvt_auth.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    try:
        session.ensure_private_auth()
    except TransientExchangeError as exc:
        assert "private auth failed after 2 attempts" in str(exc)
    else:
        raise AssertionError("TransientExchangeError was not raised")


def test_auth_and_post_authenticates_before_private_post() -> None:
    session = auth_session(1)
    calls: list[str] = []

    def fake_ensure_private_auth():
        calls.append("auth")

    def fake_auth_and_post(path: str, payload: dict):
        calls.append("post")
        return {"ok": True}

    session.ensure_private_auth = fake_ensure_private_auth
    session._client._auth_and_post = fake_auth_and_post

    result = session.auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post"]


def test_auth_and_post_retries_once_on_401() -> None:
    session = auth_session(1)
    calls: list[str] = []

    class UnauthorizedError(Exception):
        def __init__(self) -> None:
            self.response = SimpleNamespace(status_code=401)

    def fake_ensure_private_auth():
        calls.append("auth")

    def fake_auth_and_post(path: str, payload: dict):
        calls.append("post")
        if calls.count("post") == 1:
            raise UnauthorizedError()
        return {"ok": True}

    session.ensure_private_auth = fake_ensure_private_auth
    session._client._auth_and_post = fake_auth_and_post

    result = session.auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post", "auth", "post"]


def test_auth_and_post_retries_once_on_unauthenticated_payload() -> None:
    session = auth_session(1)
    calls: list[str] = []

    def fake_ensure_private_auth():
        calls.append("auth")

    def fake_auth_and_post(path: str, payload: dict):
        calls.append("post")
        if calls.count("post") == 1:
            return {
                "code": 1000,
                "message": "You need to authenticate prior to using this functionality",
                "status": 401,
            }
        return {"ok": True}

    session.ensure_private_auth = fake_ensure_private_auth
    session._client._auth_and_post = fake_auth_and_post

    result = session.auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post", "auth", "post"]


def test_ensure_private_auth_updates_sdk_session_headers(monkeypatch) -> None:
    session = auth_session(1)

    def fake_post(*args, **kwargs):
        return SimpleNamespace(
            ok=True,
            headers={
                "Set-Cookie": "gravity=session; expires=Wed, 18 Mar 2026 12:00:00 GMT",
                "X-Grvt-Account-Id": "abc123",
            },
            text="",
        )

    monkeypatch.setattr("gravity_dca.grvt_auth.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.grvt_auth.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    session.ensure_private_auth()

    assert session._client._cookie is not None
    assert session._client._cookie["gravity"] == "session"
    assert session._client._session.cookies["gravity"] == "session"
    assert session._client._session.headers["X-Grvt-Account-Id"] == "abc123"


def test_ensure_private_auth_reports_invalid_api_key_clearly(monkeypatch) -> None:
    session = auth_session(1)

    def fake_post(*args, **kwargs):
        return SimpleNamespace(
            ok=True,
            headers={},
            text='{"error":"ent: api_key not found","status":"failure"}',
        )

    monkeypatch.setattr("gravity_dca.grvt_auth.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.grvt_auth.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    try:
        session.ensure_private_auth()
    except ValueError as exc:
        assert "invalid or unknown API key" in str(exc)
        assert "api_key not found" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")


def test_get_candles_parses_and_sorts_results() -> None:
    client = SimpleNamespace(
        fetch_ohlcv=lambda **kwargs: {
            "result": [
                {
                    "instrument": "ETH_USDT_Perp",
                    "open_time": "200",
                    "close_time": "299",
                    "open": "2010.0",
                    "high": "2020.0",
                    "low": "2005.0",
                    "close": "2015.0",
                    "volume_u": "1.4",
                    "volume_q": "2821.0",
                    "trades": "11",
                },
                {
                    "instrument": "ETH_USDT_Perp",
                    "open_time": "100",
                    "close_time": "199",
                    "open": "2000.0",
                    "high": "2012.0",
                    "low": "1995.0",
                    "close": "2010.0",
                    "volume_u": "1.2",
                    "volume_q": "2412.0",
                    "trades": "9",
                },
            ]
        }
    )
    auth = SimpleNamespace(is_transient_request_error=lambda exc: False)
    market = GrvtMarketData(client=client, auth=auth, logger=logging.getLogger("gravity_dca"))

    candles = market.get_candles("ETH_USDT_Perp", timeframe="5m", limit=2)

    assert [candle.open_time for candle in candles] == [100, 200]
    assert candles[0].symbol == "ETH_USDT_Perp"
    assert candles[0].open == Decimal("2000.0")
    assert candles[0].high == Decimal("2012.0")
    assert candles[0].low == Decimal("1995.0")
    assert candles[0].close == Decimal("2010.0")
    assert candles[0].volume == Decimal("1.2")
    assert candles[0].quote_volume == Decimal("2412.0")
    assert candles[0].trades == 9


def test_get_candles_wraps_transient_exchange_errors() -> None:
    class FakeClient:
        def fetch_ohlcv(self, **kwargs):
            raise requests.exceptions.SSLError("temporary ssl failure")

    auth = SimpleNamespace(
        is_transient_request_error=lambda exc: isinstance(exc, requests.exceptions.SSLError)
    )
    market = GrvtMarketData(
        client=FakeClient(),
        auth=auth,
        logger=logging.getLogger("gravity_dca"),
    )

    try:
        market.get_candles("ETH_USDT_Perp", timeframe="5m")
    except TransientExchangeError as exc:
        assert "GRVT fetch_ohlcv failed for ETH_USDT_Perp timeframe=5m" in str(exc)
    else:
        raise AssertionError("TransientExchangeError was not raised")
