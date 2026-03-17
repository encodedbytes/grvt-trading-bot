from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import subprocess

from gravity_dca import dashboard
from gravity_dca.config import load_config_text
from gravity_dca.state import BotState
import pytest


def write_config(path: Path, *, state_file: str) -> None:
    path.write_text(
        f"""
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "500"
safety_order_quote_amount = "500"
max_safety_orders = 3
price_deviation_percent = "2.5"
take_profit_percent = "2.0"
order_type = "market"
stop_loss_percent = "10.0"
max_cycles = 5
state_file = "{state_file}"

[runtime]
dry_run = false
poll_seconds = 30
"""
    )


def test_summarize_bot_container_with_active_cycle(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.eth.toml"
    state_path = tmp_path / "state" / ".gravity-dca-eth.json"
    write_config(config_path, state_file="/state/.gravity-dca-eth.json")

    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=dashboard.datetime.now(tz=dashboard.UTC),
        quantity=Decimal("2.11"),
        price=Decimal("2125.06"),
        order_id="0x01",
        client_order_id="123",
        leverage=Decimal("10"),
        margin_type="CROSS",
    )
    state.add_safety_fill(
        quantity=Decimal("0.50"),
        price=Decimal("2060.00"),
        order_id="0x02",
        client_order_id="124",
    )
    from gravity_dca.state import save_state

    save_state(state_path, state)

    monkeypatch.setattr(dashboard, "_load_recent_log_info", lambda name: (None, "ok"))
    monkeypatch.setattr(dashboard, "_fetch_bot_status_from_api", lambda container, port: None)
    container = dashboard.DockerContainer(
        id="abc123",
        name="grvt-dca-eth",
        image="gravity-dca-bot:local",
        status="Up 2 minutes",
        config_source=config_path,
        state_source=tmp_path / "state",
        network_ips=[],
    )

    summary = dashboard.summarize_bot_container(container)

    assert summary["symbol"] == "ETH_USDT_Perp"
    assert summary["container_state"] == "running"
    assert summary["lifecycle_state"] == "active"
    assert summary["active_cycle"]["completed_safety_orders"] == 1
    assert summary["thresholds"]["take_profit_price"] is not None
    assert summary["bot_api_port"] == 8787


def test_collect_dashboard_payload_counts_inactive_max_cycles(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "list_running_bot_containers",
        lambda: [],
    )
    payload = dashboard.collect_dashboard_payload()
    assert payload["summary"]["total_containers"] == 0
    assert payload["bots"] == []


def test_collect_dashboard_payload_reports_docker_error(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard,
        "list_running_bot_containers",
        lambda: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, ["docker", "ps"], stderr="permission denied")
        ),
    )
    payload = dashboard.collect_dashboard_payload()
    assert payload["summary"]["total_containers"] == 0
    assert payload["error"] is not None


def test_docker_bin_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("GRAVITY_DASHBOARD_DOCKER_BIN", "/custom/docker")
    assert dashboard._docker_bin() == "/custom/docker"


def test_docker_bin_raises_actionable_error_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("GRAVITY_DASHBOARD_DOCKER_BIN", raising=False)
    monkeypatch.setattr(dashboard.shutil, "which", lambda name: None)

    with pytest.raises(FileNotFoundError, match="docker CLI not found on PATH"):
        dashboard._docker_bin()


def test_docker_socket_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("GRAVITY_DASHBOARD_DOCKER_SOCKET", "/custom/docker.sock")
    assert dashboard._docker_socket_path() == "/custom/docker.sock"


def test_docker_socket_uses_docker_host(monkeypatch) -> None:
    monkeypatch.delenv("GRAVITY_DASHBOARD_DOCKER_SOCKET", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/test-docker.sock")
    assert dashboard._docker_socket_path() == "/var/run/test-docker.sock"


def test_load_config_text_can_preserve_container_state_path() -> None:
    config = load_config_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "500"
safety_order_quote_amount = "500"
max_safety_orders = 3
price_deviation_percent = "2.5"
take_profit_percent = "2.0"
state_file = "/state/test.json"

[runtime]
dry_run = false
""",
        config_path="/app/config.toml",
        resolve_state_paths=False,
    )
    assert str(config.dca.state_file) == "/state/test.json"


def test_summarize_bot_container_loads_config_from_container_when_host_path_missing(
    tmp_path, monkeypatch
) -> None:
    state = BotState()
    state.start_cycle(
        symbol="ETH_USDT_Perp",
        side="buy",
        when=dashboard.datetime.now(tz=dashboard.UTC),
        quantity=Decimal("1.0"),
        price=Decimal("2000"),
        order_id="0x01",
        client_order_id="abc",
    )
    config_text = """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "500"
safety_order_quote_amount = "500"
max_safety_orders = 3
price_deviation_percent = "2.5"
take_profit_percent = "2.0"
order_type = "market"
max_cycles = 5
state_file = "/state/test.json"

[runtime]
dry_run = false
poll_seconds = 30
"""
    state_text = """
{
  "active_cycle": {
    "symbol": "ETH_USDT_Perp",
    "side": "buy",
    "started_at": "2026-03-16T00:00:00+00:00",
    "total_quantity": "1.0",
    "total_cost": "2000.0",
    "average_entry_price": "2000.0",
    "completed_safety_orders": 0,
    "last_order_id": "0x01",
    "last_client_order_id": "abc"
  },
  "completed_cycles": 0,
  "last_closed_cycle": null
}
"""

    def fake_read_file(container_id: str, path: str) -> bytes:
        assert container_id == "abc123"
        if path == "/app/config.toml":
            return config_text.encode("utf-8")
        if path == "/state/test.json":
            return state_text.encode("utf-8")
        raise FileNotFoundError(path)

    monkeypatch.setattr(dashboard, "_docker_api_read_file", fake_read_file)
    monkeypatch.setattr(dashboard, "_load_recent_log_info", lambda name: (None, "ok"))
    monkeypatch.setattr(dashboard, "_fetch_bot_status_from_api", lambda container, port: None)
    container = dashboard.DockerContainer(
        id="abc123",
        name="grvt-dca-eth",
        image="gravity-dca-bot:local",
        status="Up 2 minutes",
        config_source=tmp_path / "missing-config.toml",
        state_source=tmp_path / "state",
        network_ips=[],
    )

    summary = dashboard.summarize_bot_container(container)

    assert summary["symbol"] == "ETH_USDT_Perp"
    assert summary["active_cycle"] is not None
    assert summary["state_file"] == "/state/test.json"


def test_summarize_bot_container_prefers_bot_api(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.btc.toml"
    config_path.write_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "BTC_USDT_Perp"
side = "buy"
initial_quote_amount = "1000"
safety_order_quote_amount = "1000"
max_safety_orders = 3
price_deviation_percent = "2.0"
take_profit_percent = "1.4"
order_type = "market"
max_cycles = 10
state_file = "/state/btc.json"

[runtime]
dry_run = false
poll_seconds = 30
bot_api_port = 8787
"""
    )
    monkeypatch.setattr(dashboard, "_load_recent_log_info", lambda name: ("api-error", "log line"))
    monkeypatch.setattr(
        dashboard,
        "_fetch_bot_status_from_api",
        lambda container, port: {
            "symbol": "BTC_USDT_Perp",
            "environment": "prod",
            "order_type": "market",
            "dry_run": False,
            "state_file": "/state/btc.json",
            "lifecycle_state": "active",
            "initial_leverage": "5",
            "margin_type": "CROSS",
            "poll_seconds": 30,
            "bot_api_port": 8787,
            "initial_quote_amount": "1000",
            "safety_order_quote_amount": "1000",
            "max_safety_orders": 3,
            "price_deviation_percent": "2.0",
            "take_profit_percent": "1.4",
            "stop_loss_percent": "7.5",
            "safety_order_step_scale": "1",
            "safety_order_volume_scale": "1",
            "telegram_enabled": True,
            "completed_cycles": 5,
            "max_cycles": 10,
            "active_cycle": {"side": "buy"},
            "thresholds": {
                "take_profit_price": "75000",
                "stop_loss_price": "69000",
                "next_safety_trigger_price": "72000",
            },
            "last_closed_cycle": None,
            "runtime_status": {"last_iteration_error": "ValueError: boom"},
        },
    )
    container = dashboard.DockerContainer(
        id="abc123",
        name="grvt-dca-btc",
        image="gravity-dca-bot:local",
        status="Up 2 minutes",
        config_source=config_path,
        state_source=tmp_path / "state",
        network_ips=["172.18.0.3"],
    )

    summary = dashboard.summarize_bot_container(container)

    assert summary["symbol"] == "BTC_USDT_Perp"
    assert summary["recent_error"] == "ValueError: boom"
    assert summary["last_log_line"] == "log line"
    assert summary["bot_api_port"] == 8787


def test_summarize_bot_container_uses_configured_api_port(monkeypatch, tmp_path) -> None:
    seen = {}
    config_path = tmp_path / "config.eth.toml"
    config_path.write_text(
        """
[credentials]
api_key = "key"
private_key = "priv"
trading_account_id = "acct"
environment = "prod"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "500"
safety_order_quote_amount = "500"
max_safety_orders = 3
price_deviation_percent = "2.5"
take_profit_percent = "2.0"
order_type = "market"
stop_loss_percent = "10.0"
max_cycles = 5
state_file = "/state/.gravity-dca-eth.json"

[runtime]
dry_run = false
poll_seconds = 30
bot_api_port = 8899
"""
    )
    monkeypatch.setattr(dashboard, "_load_recent_log_info", lambda name: (None, "ok"))

    def fake_fetch(container, port):
        seen["port"] = port
        return None

    monkeypatch.setattr(dashboard, "_fetch_bot_status_from_api", fake_fetch)
    container = dashboard.DockerContainer(
        id="abc123",
        name="grvt-dca-eth",
        image="gravity-dca-bot:local",
        status="Up 2 minutes",
        config_source=config_path,
        state_source=tmp_path / "state",
        network_ips=["172.18.0.2"],
    )

    dashboard.summarize_bot_container(container)

    assert seen["port"] == 8899


def test_dashboard_html_escapes_js_newline_sequence() -> None:
    assert 'join("\\n")' in dashboard.HTML_PAGE


def test_dashboard_html_focuses_logs_when_drawer_opens() -> None:
    assert 'var focusLogsOnDrawerOpen = false;' in dashboard.HTML_PAGE
    assert 'logsElement.scrollIntoView({ block: "end" });' in dashboard.HTML_PAGE


def test_dashboard_html_has_logs_autoscroll_toggle() -> None:
    assert 'id="drawer-autoscroll"' in dashboard.HTML_PAGE
    assert 'Auto-scroll' in dashboard.HTML_PAGE
    assert 'function shouldAutoScrollLogs()' in dashboard.HTML_PAGE
    assert 'if (shouldAutoScrollLogs()) {' in dashboard.HTML_PAGE


def test_dashboard_html_uses_dark_theme_and_accessible_controls() -> None:
    assert 'color-scheme: dark;' in dashboard.HTML_PAGE
    assert 'class="skip-link"' in dashboard.HTML_PAGE
    assert 'aria-live="polite"' in dashboard.HTML_PAGE
    assert 'class="card-button" data-container="' in dashboard.HTML_PAGE
    assert 'type="button" aria-label="Open details for ' in dashboard.HTML_PAGE


def test_dashboard_html_has_view_toggle() -> None:
    assert 'View</span>' in dashboard.HTML_PAGE
    assert 'id="view-vertical"' in dashboard.HTML_PAGE
    assert 'id="view-horizontal"' in dashboard.HTML_PAGE
    assert 'data-view="horizontal"' in dashboard.HTML_PAGE
    assert 'function applyViewMode(view)' in dashboard.HTML_PAGE
    assert 'gravity-dashboard-view' in dashboard.HTML_PAGE
    assert 'var latestBots = [];' in dashboard.HTML_PAGE
    assert 'function renderCards(bots, errorMessage) {' in dashboard.HTML_PAGE
    assert 'if (selectedView === "horizontal") {' in dashboard.HTML_PAGE
    assert 'function renderHorizontalBot(bot, statusBadges)' in dashboard.HTML_PAGE


def test_dashboard_html_closes_drawer_on_escape() -> None:
    assert 'if (event.key === "Escape" && selectedBot) {' in dashboard.HTML_PAGE
    assert 'closeDrawer();' in dashboard.HTML_PAGE


def test_dashboard_html_shows_bot_api_port_in_drawer() -> None:
    assert 'field("Bot API port", bot.bot_api_port)' in dashboard.HTML_PAGE
