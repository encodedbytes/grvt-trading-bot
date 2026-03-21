from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .grid_state import GridBotState, load_grid_state
from .momentum_state import load_momentum_state
from .state import BotState, load_state
from .status_snapshot import (
    RuntimeStatus,
    build_status_snapshot,
    detect_risk_reduce_only_reason,
    new_runtime_status,
)


API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8787


@dataclass
class SharedBotStatus:
    config: AppConfig
    logger: logging.Logger
    runtime: RuntimeStatus
    lock: threading.Lock

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            runtime = RuntimeStatus(
                started_at=self.runtime.started_at,
                last_iteration_started_at=self.runtime.last_iteration_started_at,
                last_iteration_completed_at=self.runtime.last_iteration_completed_at,
                last_iteration_succeeded_at=self.runtime.last_iteration_succeeded_at,
                last_iteration_error=self.runtime.last_iteration_error,
                last_iteration_error_at=self.runtime.last_iteration_error_at,
                risk_reduce_only=self.runtime.risk_reduce_only,
                risk_reduce_only_reason=self.runtime.risk_reduce_only_reason,
                risk_reduce_only_at=self.runtime.risk_reduce_only_at,
                strategy_status=self.runtime.strategy_status,
            )
        if self.config.strategy_type == "momentum":
            if self.config.momentum is None:
                raise ValueError("Momentum config is required for momentum bot API snapshots")
            state = load_momentum_state(self.config.momentum.state_file)
        elif self.config.strategy_type == "grid":
            if self.config.grid is None:
                raise ValueError("Grid config is required for grid bot API snapshots")
            state = load_grid_state(self.config.grid.state_file)
        else:
            if self.config.dca is None:
                raise ValueError("DCA config is required for DCA bot API snapshots")
            state = load_state(self.config.dca.state_file)
        return build_status_snapshot(self.config, state, runtime)

    def mark_iteration_started(self, when: str) -> None:
        with self.lock:
            self.runtime.last_iteration_started_at = when

    def mark_iteration_succeeded(self, when: str) -> None:
        with self.lock:
            self.runtime.last_iteration_completed_at = when
            self.runtime.last_iteration_succeeded_at = when
            self.runtime.last_iteration_error = None
            self.runtime.last_iteration_error_at = None
            self.runtime.risk_reduce_only = False
            self.runtime.risk_reduce_only_reason = None
            self.runtime.risk_reduce_only_at = None

    def set_strategy_status(self, payload: dict[str, Any] | None) -> None:
        with self.lock:
            self.runtime.strategy_status = payload

    def mark_iteration_failed(self, when: str, error: Exception) -> None:
        with self.lock:
            self.runtime.last_iteration_completed_at = when
            self.runtime.last_iteration_error = f"{type(error).__name__}: {error}"
            self.runtime.last_iteration_error_at = when
            self.runtime.strategy_status = None
            risk_reduce_only_reason = detect_risk_reduce_only_reason(error)
            self.runtime.risk_reduce_only = risk_reduce_only_reason is not None
            self.runtime.risk_reduce_only_reason = risk_reduce_only_reason
            self.runtime.risk_reduce_only_at = when if risk_reduce_only_reason is not None else None


class _BotApiHandler(BaseHTTPRequestHandler):
    shared: SharedBotStatus

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if parsed.path == "/status":
            self._send_json(200, self.shared.snapshot())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        self.shared.logger.debug(format, *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
class BotApiServer(AbstractContextManager["BotApiServer"]):
    def __init__(
        self,
        shared: SharedBotStatus,
        *,
        host: str = API_HOST,
        port: int = DEFAULT_API_PORT,
    ) -> None:
        handler = type("BotApiHandler", (_BotApiHandler,), {"shared": shared})
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._logger = shared.logger
        self._host = host
        self._port = port

    def start(self) -> None:
        self._thread.start()
        self._logger.info("Bot API listening on http://%s:%s", self._host, self._port)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self) -> BotApiServer:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def build_shared_status(config: AppConfig, logger: logging.Logger) -> SharedBotStatus:
    return SharedBotStatus(
        config=config,
        logger=logger,
        runtime=new_runtime_status(),
        lock=threading.Lock(),
    )
