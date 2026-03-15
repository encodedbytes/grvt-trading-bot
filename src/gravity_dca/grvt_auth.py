from __future__ import annotations

from datetime import datetime
from http.cookies import SimpleCookie
import logging
import time

import requests
from pysdk.grvt_ccxt import GrvtCcxt
from pysdk.grvt_ccxt_env import GrvtEnv, get_grvt_endpoint

from .grvt_models import TransientExchangeError


class GrvtPrivateSession:
    def __init__(
        self,
        *,
        env: GrvtEnv,
        api_key: str,
        client: GrvtCcxt,
        logger: logging.Logger,
        retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> None:
        self._env = env
        self._api_key = api_key
        self._client = client
        self._logger = logger
        self._retry_attempts = max(retry_attempts, 1)
        self._retry_backoff_seconds = max(retry_backoff_seconds, 0)

    def _is_retryable_auth_http_status(self, status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def is_transient_request_error(self, exc: Exception) -> bool:
        if isinstance(exc, requests.exceptions.SSLError):
            return True
        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        return False

    def _is_unauthenticated_payload(self, response: dict) -> bool:
        status = response.get("status")
        code = response.get("code")
        message = str(response.get("message", "")).lower()
        return status == 401 or code == 1000 and "authenticate prior" in message

    def _sync_sdk_auth_session(self, response: requests.Response) -> None:
        cookie = SimpleCookie()
        cookie.load(response.headers.get("Set-Cookie", ""))
        if "gravity" not in cookie:
            raise ValueError(f"GRVT auth did not return a session cookie: {response.text[:200]}")
        expires_at = datetime.strptime(
            cookie["gravity"]["expires"],
            "%a, %d %b %Y %H:%M:%S %Z",
        ).timestamp()
        account_id = response.headers.get("X-Grvt-Account-Id", "")
        self._client._cookie = {
            "gravity": cookie["gravity"].value,
            "expires": expires_at,
            "X-Grvt-Account-Id": account_id,
        }
        self._client._session.cookies.update({"gravity": cookie["gravity"].value})
        if account_id:
            self._client._session.headers.update({"X-Grvt-Account-Id": account_id})

    def clear_sdk_cookie(self) -> None:
        self._client._cookie = None

    def ensure_private_auth(self) -> None:
        auth_url = get_grvt_endpoint(self._env, "AUTH")
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
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
                        and attempt < self._retry_attempts
                    ):
                        self._logger.warning(
                            "Retrying GRVT private auth after HTTP %s attempt=%s/%s",
                            response.status_code,
                            attempt,
                            self._retry_attempts,
                        )
                        time.sleep(self._retry_backoff_seconds * attempt)
                        continue
                    raise ValueError(message)
                self._sync_sdk_auth_session(response)
                return
            except Exception as exc:
                last_error = exc
                if self.is_transient_request_error(exc) and attempt < self._retry_attempts:
                    self._logger.warning(
                        "Retrying GRVT private auth after transient error attempt=%s/%s error=%s",
                        attempt,
                        self._retry_attempts,
                        exc,
                    )
                    time.sleep(self._retry_backoff_seconds * attempt)
                    continue
                if self.is_transient_request_error(exc):
                    raise TransientExchangeError(
                        f"GRVT private auth failed after {attempt} attempts: {exc}"
                    ) from exc
                raise
        if last_error is not None:
            raise TransientExchangeError(
                f"GRVT private auth failed after {self._retry_attempts} attempts: {last_error}"
            ) from last_error

    def auth_and_post(self, path: str, payload: dict) -> dict:
        self.ensure_private_auth()
        try:
            response = self._client._auth_and_post(path, payload)
        except Exception as exc:
            response = getattr(exc, "response", None)
            if response is not None and getattr(response, "status_code", None) == 401:
                self._logger.warning(
                    "GRVT private POST returned 401, refreshing auth and retrying once. path=%s",
                    path,
                )
                self.clear_sdk_cookie()
                self.ensure_private_auth()
                return self._client._auth_and_post(path, payload)
            if self.is_transient_request_error(exc):
                raise TransientExchangeError(f"GRVT request failed for {path}: {exc}") from exc
            raise
        if self._is_unauthenticated_payload(response):
            self._logger.warning(
                "GRVT private POST returned unauthenticated payload, refreshing auth and retrying once. "
                "path=%s response=%s",
                path,
                response,
            )
            self.clear_sdk_cookie()
            self.ensure_private_auth()
            return self._client._auth_and_post(path, payload)
        return response
