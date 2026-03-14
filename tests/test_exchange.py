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
    return instance


def test_ensure_private_auth_retries_transient_ssl_errors(monkeypatch) -> None:
    client = exchange(3)
    calls = {"count": 0}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.SSLError("unexpected eof")
        return SimpleNamespace(ok=True, headers={"Set-Cookie": "gravity=session"}, text="")

    monkeypatch.setattr("gravity_dca.exchange.requests.post", fake_post)

    monkeypatch.setattr("gravity_dca.exchange.get_grvt_endpoint", lambda env, endpoint: "https://edge.grvt.io/auth/api_key/login")

    client.ensure_private_auth()

    assert calls["count"] == 3


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
