from __future__ import annotations

import logging
from types import SimpleNamespace

import requests

from gravity_dca.exchange import GrvtExchange, TransientExchangeError


def exchange(attempts: int) -> GrvtExchange:
    instance = GrvtExchange.__new__(GrvtExchange)
    instance._logger = logging.getLogger("gravity_dca")
    instance._env = object()
    instance._api_key = "key"
    instance._private_auth_retry_attempts = attempts
    instance._private_auth_retry_backoff_seconds = 0
    instance._client = SimpleNamespace(
        _session=SimpleNamespace(cookies={}, headers={}),
        _cookie=None,
    )
    return instance


def test_ensure_private_auth_retries_transient_ssl_errors(monkeypatch) -> None:
    client = exchange(3)
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

    monkeypatch.setattr("gravity_dca.exchange.requests.post", fake_post)

    monkeypatch.setattr("gravity_dca.exchange.get_grvt_endpoint", lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login")

    client.ensure_private_auth()

    assert calls["count"] == 3
    assert client._client._cookie is not None
    assert client._client._session.cookies["gravity"] == "session"


def test_ensure_private_auth_raises_transient_exchange_error_after_retries(monkeypatch) -> None:
    client = exchange(2)

    def fake_post(*args, **kwargs):
        raise requests.exceptions.SSLError("unexpected eof")

    monkeypatch.setattr("gravity_dca.exchange.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.exchange.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    try:
        client.ensure_private_auth()
    except TransientExchangeError as exc:
        assert "private auth failed after 2 attempts" in str(exc)
    else:
        raise AssertionError("TransientExchangeError was not raised")


def test_auth_and_post_authenticates_before_private_post(monkeypatch) -> None:
    client = exchange(1)
    calls: list[str] = []

    def fake_ensure_private_auth():
        calls.append("auth")

    def fake_auth_and_post(path: str, payload: dict):
        calls.append("post")
        return {"ok": True}

    client.ensure_private_auth = fake_ensure_private_auth
    client._client._auth_and_post = fake_auth_and_post

    result = client._auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post"]


def test_auth_and_post_retries_once_on_401(monkeypatch) -> None:
    client = exchange(1)
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

    client.ensure_private_auth = fake_ensure_private_auth
    client._client._auth_and_post = fake_auth_and_post

    result = client._auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post", "auth", "post"]


def test_auth_and_post_retries_once_on_unauthenticated_payload() -> None:
    client = exchange(1)
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

    client.ensure_private_auth = fake_ensure_private_auth
    client._client._auth_and_post = fake_auth_and_post

    result = client._auth_and_post("https://edge.grvt.io/private", {"hello": "world"})

    assert result == {"ok": True}
    assert calls == ["auth", "post", "auth", "post"]


def test_ensure_private_auth_updates_sdk_session_headers(monkeypatch) -> None:
    client = exchange(1)

    def fake_post(*args, **kwargs):
        return SimpleNamespace(
            ok=True,
            headers={
                "Set-Cookie": "gravity=session; expires=Wed, 18 Mar 2026 12:00:00 GMT",
                "X-Grvt-Account-Id": "abc123",
            },
            text="",
        )

    monkeypatch.setattr("gravity_dca.exchange.requests.post", fake_post)
    monkeypatch.setattr(
        "gravity_dca.exchange.get_grvt_endpoint",
        lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login",
    )

    client.ensure_private_auth()

    assert client._client._cookie is not None
    assert client._client._cookie["gravity"] == "session"
    assert client._client._session.cookies["gravity"] == "session"
    assert client._client._session.headers["X-Grvt-Account-Id"] == "abc123"
