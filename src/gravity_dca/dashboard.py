from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .config import AppConfig, load_config, load_config_text
from .dashboard_payload import (
    build_container_summary,
    build_error_summary,
    normalize_status_payload,
)
from .dashboard_runtime import (
    DockerContainer,
    container_state as _container_state,
    docker_api_read_file as _docker_api_read_file,
    docker_bin as _docker_bin,
    docker_socket_path as _docker_socket_path,
    fetch_bot_status_from_api as _fetch_bot_status_from_api,
    get_container_logs,
    list_running_bot_containers,
    load_recent_log_info as _load_recent_log_info,
)
from .momentum_state import MomentumBotState, load_momentum_state, load_momentum_state_text
from .state import BotState, load_state, load_state_text
from .status_snapshot import build_status_snapshot, new_runtime_status
from .dashboard_template import HTML_PAGE


UTC = timezone.utc
LOGGER = logging.getLogger("gravity_dca.dashboard")

def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def summarize_bot_container(container: DockerContainer) -> dict[str, Any]:
    LOGGER.info("Summarizing container=%s config=%s", container.name, container.config_source)
    state: BotState | MomentumBotState = BotState()
    config: AppConfig | None = None
    config_file = container.config_source
    state_file: Path | None = None
    load_error: str | None = None
    recent_error, last_log_line = _load_recent_log_info(container.name)
    if config_file is not None:
        try:
            if config_file.exists():
                config = load_config(config_file)
            else:
                config = load_config_text(
                    _docker_api_read_file(container.id, "/app/config.toml").decode("utf-8"),
                    config_path="/app/config.toml",
                    resolve_state_paths=False,
                )
            if config.strategy_type == "momentum":
                settings = config.momentum
                if settings is None:
                    raise ValueError("Momentum config is missing [momentum] settings")
                state_file = settings.state_file
                if state_file.exists():
                    state = load_momentum_state(state_file)
                else:
                    try:
                        state = load_momentum_state_text(
                            _docker_api_read_file(container.id, str(state_file)).decode("utf-8")
                        )
                    except (FileNotFoundError, OSError, tarfile.TarError):
                        state = MomentumBotState()
                symbol = settings.symbol
                active_runtime = state.active_position is not None
            else:
                state_file = config.dca.state_file
                if state_file.exists():
                    state = load_state(state_file)
                else:
                    try:
                        state = load_state_text(
                            _docker_api_read_file(container.id, str(state_file)).decode("utf-8")
                        )
                    except (FileNotFoundError, OSError, tarfile.TarError):
                        state = BotState()
                symbol = config.dca.symbol
                active_runtime = state.active_cycle is not None
            LOGGER.info(
                "Loaded config/state for container=%s strategy=%s symbol=%s state_file=%s active_runtime=%s completed_cycles=%s",
                container.name,
                config.strategy_type,
                symbol,
                state_file,
                active_runtime,
                state.completed_cycles,
            )
        except Exception as exc:  # pragma: no cover - defensive serialization path
            load_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("Failed to load config/state for container=%s", container.name)
    status_payload = (
        _fetch_bot_status_from_api(container, port=config.runtime.bot_api_port)
        if config is not None
        else None
    )
    if status_payload is not None:
        LOGGER.info("Loaded bot status via bot API for container=%s", container.name)
        normalized = normalize_status_payload(status_payload)
        return build_container_summary(
            container_name=container.name,
            container_id=container.id,
            container_state=_container_state(container.status),
            lifecycle_state=status_payload["lifecycle_state"],
            image=container.image,
            config_file=str(config_file) if config_file is not None else "/app/config.toml",
            normalized_status=normalized,
            risk_reduce_only=status_payload["runtime_status"].get("risk_reduce_only", False),
            risk_reduce_only_reason=status_payload["runtime_status"].get("risk_reduce_only_reason"),
            recent_error=status_payload["runtime_status"]["last_iteration_error"] or recent_error,
            last_log_line=last_log_line,
        )
    if config is None:
        LOGGER.warning("Container=%s has no usable config; returning error summary", container.name)
        return build_error_summary(
            container_name=container.name,
            container_state=_container_state(container.status),
            image=container.image,
            config_file=str(config_file) if config_file is not None else "",
            state_file=str(state_file) if state_file is not None else "",
            recent_error=load_error or recent_error,
            last_log_line=last_log_line,
        )
    status_payload = build_status_snapshot(config, state, new_runtime_status())
    normalized = normalize_status_payload(status_payload)
    active_runtime = normalized["active_trade"] is not None
    LOGGER.info(
        "Container=%s lifecycle_state=%s strategy=%s active_runtime=%s",
        container.name,
        status_payload["lifecycle_state"],
        normalized["strategy_type"],
        active_runtime,
    )
    return build_container_summary(
        container_name=container.name,
        container_id=container.id,
        container_state=_container_state(container.status),
        lifecycle_state=status_payload["lifecycle_state"],
        image=container.image,
        config_file=str(config_file),
        normalized_status=normalized,
        risk_reduce_only=False,
        risk_reduce_only_reason=None,
        recent_error=recent_error,
        last_log_line=last_log_line,
    )


def collect_dashboard_payload() -> dict[str, Any]:
    error: str | None = None
    try:
        bots = [summarize_bot_container(container) for container in list_running_bot_containers()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        LOGGER.warning("Dashboard could not inspect Docker: %s", exc)
        bots = []
        error = f"Docker inspection unavailable: {exc}"
    LOGGER.info(
        "Dashboard payload generated bots=%s active=%s inactive_max=%s error=%s",
        len(bots),
        sum(1 for bot in bots if bot["active_trade"] is not None),
        sum(1 for bot in bots if bot["lifecycle_state"] == "inactive-max-cycles"),
        error,
    )
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": {
            "total_containers": len(bots),
            "active_cycles": sum(1 for bot in bots if bot["active_trade"] is not None),
            "inactive_max_cycles": sum(
                1 for bot in bots if bot["lifecycle_state"] == "inactive-max-cycles"
            ),
            "containers_with_errors": sum(1 for bot in bots if bot["recent_error"] is not None),
        },
        "bots": sorted(bots, key=lambda bot: str(bot["symbol"])),
        "error": error,
    }


def get_bot_detail(container_name: str) -> dict[str, Any] | None:
    for container in list_running_bot_containers():
        if container.name == container_name:
            return summarize_bot_container(container)
    return None


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        LOGGER.info("HTTP GET %s", self.path)
        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/bots":
            payload = json.dumps(collect_dashboard_payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/client-log":
            message = parse_qs(parsed.query).get("message", [""])[0]
            LOGGER.info("Client log: %s", message)
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path.startswith("/api/bots/"):
            suffix = parsed.path[len("/api/bots/") :]
            if suffix.endswith("/logs"):
                container_name = unquote(suffix[: -len("/logs")]).strip("/")
                LOGGER.info("Serving log detail for container=%s", container_name)
                query = parse_qs(parsed.query)
                tail = int(query.get("tail", ["200"])[0])
                payload = json.dumps(
                    {"container_name": container_name, "lines": get_container_logs(container_name, tail=tail)}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            container_name = unquote(suffix).strip("/")
            LOGGER.info("Serving detail for container=%s", container_name)
            bot = get_bot_detail(container_name)
            if bot is None:
                LOGGER.warning("No bot detail found for container=%s", container_name)
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps(bot).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        logging.getLogger("gravity_dca.dashboard").debug(format, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local web dashboard for GRVT bot containers.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", default=8080, type=int, help="Port to listen on.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    logging.getLogger("gravity_dca.dashboard").info(
        "Dashboard listening on http://%s:%s", args.host, args.port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - operator shutdown
        pass
    finally:
        server.server_close()
