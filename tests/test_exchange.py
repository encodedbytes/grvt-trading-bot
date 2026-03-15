from __future__ import annotations

import logging
from types import SimpleNamespace

import requests

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
