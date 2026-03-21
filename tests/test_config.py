from decimal import Decimal
from pathlib import Path
import re

import pytest

from gravity_dca.config import load_config, load_config_text
from gravity_dca.exchange import normalize_margin_type


def test_load_config_reads_optional_leverage_and_margin_type(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
initial_leverage = "10"
margin_type = "isolated"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"

[runtime]
dry_run = true
"""
    )

    config = load_config(config_path)

    assert config.dca.initial_leverage == Decimal("10")
    assert config.dca.margin_type == "isolated"


def test_normalize_margin_type_supports_common_aliases() -> None:
    assert normalize_margin_type("cross") == "CROSS"
    assert normalize_margin_type("isolated") == "ISOLATED"
    assert normalize_margin_type(" SIMPLE_CROSS_MARGIN ") == "CROSS"
    assert normalize_margin_type("PORTFOLIO_CROSS_MARGIN") == "CROSS"


def test_load_config_reads_limit_order_settings(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
order_type = "limit"
limit_price_offset_percent = "0.2"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"

[runtime]
dry_run = true
limit_ttl_seconds = 45
"""
    )

    config = load_config(config_path)

    assert config.dca.order_type == "limit"
    assert config.dca.limit_price_offset_percent == Decimal("0.2")
    assert config.runtime.limit_ttl_seconds == 45


def test_load_config_reads_bot_api_port(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"

[runtime]
dry_run = true
bot_api_port = 8899
"""
    )

    config = load_config(config_path)

    assert config.runtime.bot_api_port == 8899


def test_load_config_maps_container_state_path_to_local_state_dir(tmp_path) -> None:
    (tmp_path / "state").mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"
state_file = "/state/.gravity-dca-eth.json"

[runtime]
dry_run = true
"""
    )

    config = load_config(config_path)

    assert config.dca.state_file == tmp_path / "state" / ".gravity-dca-eth.json"


def test_load_config_maps_nested_local_config_to_repo_state_dir(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "state").mkdir()
    local_configs_dir = repo_root / "local-configs"
    local_configs_dir.mkdir()
    config_path = local_configs_dir / "config.btc.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "BTC_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"
state_file = "/state/.gravity-dca-btc.json"

[runtime]
dry_run = true
"""
    )

    config = load_config(config_path)

    assert config.dca.state_file == repo_root / "state" / ".gravity-dca-btc.json"


def test_load_config_preserves_container_state_path_when_parent_exists(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"
state_file = "/state/.gravity-dca-eth.json"

[runtime]
dry_run = true
"""
    )

    original_exists = type(Path()).exists

    def fake_exists(path: Path) -> bool:
        if path == Path("/state"):
            return True
        if path == Path("/state/.gravity-dca-eth.json"):
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    config = load_config(config_path)

    assert config.dca.state_file == Path("/state/.gravity-dca-eth.json")


def test_load_config_reads_optional_telegram_settings(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"

[telegram]
enabled = true
bot_token = "bot-token"
chat_id = "12345"
send_startup_summary = false
notify_position_config_changes = false
error_notification_cooldown_seconds = 120

[runtime]
dry_run = true
private_auth_retry_attempts = 5
private_auth_retry_backoff_seconds = 4
"""
    )

    config = load_config(config_path)

    assert config.telegram.enabled is True
    assert config.telegram.bot_token == "bot-token"
    assert config.telegram.chat_id == "12345"
    assert config.telegram.send_startup_summary is False
    assert config.telegram.notify_position_config_changes is False
    assert config.telegram.error_notification_cooldown_seconds == 120
    assert config.runtime.private_auth_retry_attempts == 5
    assert config.runtime.private_auth_retry_backoff_seconds == 4


def test_load_config_reads_momentum_settings(tmp_path) -> None:
    config_path = tmp_path / "config.momentum.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
order_type = "limit"
limit_price_offset_percent = "0.05"
initial_leverage = "5"
margin_type = "cross"
max_cycles = 5
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
use_trend_failure_exit = true
take_profit_percent = "4.5"
state_file = "/state/.gravity-momentum-eth.json"

[runtime]
dry_run = true
"""
    )

    config = load_config(config_path)

    assert config.strategy_type == "momentum"
    assert config.dca is None
    assert config.momentum is not None
    assert config.momentum.symbol == "ETH_USDT_Perp"
    assert config.momentum.quote_amount == Decimal("500")
    assert config.momentum.order_type == "limit"
    assert config.momentum.limit_price_offset_percent == Decimal("0.05")
    assert config.momentum.initial_leverage == Decimal("5")
    assert config.momentum.margin_type == "cross"
    assert config.momentum.max_cycles == 5
    assert config.momentum.timeframe == "5m"
    assert config.momentum.ema_fast_period == 20
    assert config.momentum.ema_slow_period == 50
    assert config.momentum.breakout_lookback == 20
    assert config.momentum.adx_period == 14
    assert config.momentum.min_adx == Decimal("20")
    assert config.momentum.atr_period == 14
    assert config.momentum.min_atr_percent == Decimal("0.4")
    assert config.momentum.stop_atr_multiple == Decimal("1.5")
    assert config.momentum.trailing_atr_multiple == Decimal("2.0")
    assert config.momentum.use_trend_failure_exit is True
    assert config.momentum.take_profit_percent == Decimal("4.5")
    assert config.momentum.state_file == tmp_path / "state" / ".gravity-momentum-eth.json"


def test_load_config_reads_selector_style_momentum_settings() -> None:
    config = load_config_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[strategy]
type = "momentum"

[strategy.momentum]
symbol = "BTC_USDT_Perp"
quote_amount = "250"
timeframe = "15m"
ema_fast_period = 12
ema_slow_period = 26
breakout_lookback = 10
adx_period = 14
min_adx = "18"
atr_period = 14
min_atr_percent = "0.3"
stop_atr_multiple = "1.2"
trailing_atr_multiple = "1.8"

[runtime]
dry_run = true
""",
        resolve_state_paths=False,
    )

    assert config.strategy_type == "momentum"
    assert config.momentum is not None
    assert config.momentum.symbol == "BTC_USDT_Perp"
    assert config.momentum.side == "buy"
    assert config.momentum.order_type == "market"
    assert config.momentum.state_file == Path(".gravity-momentum-state.json")


def test_load_config_reads_grid_settings(tmp_path) -> None:
    config_path = tmp_path / "config.grid.toml"
    config_path.write_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
side = "buy"
order_type = "limit"
seed_enabled = true
initial_leverage = "3"
margin_type = "cross"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 8
spacing_mode = "arithmetic"
quote_amount_per_level = "100"
max_active_buy_orders = 3
max_inventory_levels = 4
state_file = "/state/.gravity-grid-eth.json"

[runtime]
dry_run = true
"""
    )

    config = load_config(config_path)

    assert config.strategy_type == "grid"
    assert config.dca is None
    assert config.momentum is None
    assert config.grid is not None
    assert config.grid.symbol == "ETH_USDT_Perp"
    assert config.grid.side == "buy"
    assert config.grid.order_type == "limit"
    assert config.grid.initial_leverage == Decimal("3")
    assert config.grid.margin_type == "cross"
    assert config.grid.price_band_low == Decimal("1800")
    assert config.grid.price_band_high == Decimal("2200")
    assert config.grid.grid_levels == 8
    assert config.grid.spacing_mode == "arithmetic"
    assert config.grid.quote_amount_per_level == Decimal("100")
    assert config.grid.max_active_buy_orders == 3
    assert config.grid.max_inventory_levels == 4
    assert config.grid.seed_enabled is True
    assert config.grid.state_file == tmp_path / "state" / ".gravity-grid-eth.json"


def test_load_config_reads_selector_style_grid_settings() -> None:
    config = load_config_text(
        """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[strategy]
type = "grid"

[strategy.grid]
symbol = "BTC_USDT_Perp"
price_band_low = "80000"
price_band_high = "95000"
grid_levels = 6
quote_amount_per_level = "50"
max_active_buy_orders = 2
max_inventory_levels = 2
""",
        resolve_state_paths=False,
    )

    assert config.strategy_type == "grid"
    assert config.grid is not None
    assert config.grid.symbol == "BTC_USDT_Perp"
    assert config.grid.side == "buy"
    assert config.grid.order_type == "limit"
    assert config.grid.spacing_mode == "arithmetic"
    assert config.grid.seed_enabled is False
    assert config.grid.state_file == Path(".gravity-grid-state.json")


def test_load_config_reports_friendly_error_for_null_values() -> None:
    with pytest.raises(
        ValueError,
        match=re.escape(
            "TOML does not support `null`; remove the key entirely to leave an optional value unset."
        ),
    ):
        load_config_text(
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
take_profit_percent = null
""",
            config_path="config.momentum.toml",
            resolve_state_paths=False,
        )


@pytest.mark.parametrize(
    ("raw_text", "message"),
    [
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"
""",
            "config must define either a [dca], [momentum], or [grid] section",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"

[momentum]
symbol = "ETH_USDT_Perp"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
""",
            "config cannot define more than one strategy section",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[strategy]
type = "momentum"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"
""",
            "strategy.type = 'momentum' requires a [momentum] section",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[momentum]
symbol = "ETH_USDT_Perp"
side = "sell"
quote_amount = "500"
timeframe = "5m"
ema_fast_period = 20
ema_slow_period = 50
breakout_lookback = 20
adx_period = 14
min_adx = "20"
atr_period = 14
min_atr_percent = "0.4"
stop_atr_multiple = "1.5"
trailing_atr_multiple = "2.0"
""",
            "momentum side must be 'buy'",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[strategy]
type = "grid"

[dca]
symbol = "ETH_USDT_Perp"
side = "buy"
initial_quote_amount = "25"
safety_order_quote_amount = "25"
max_safety_orders = 2
price_deviation_percent = "2.0"
take_profit_percent = "1.0"
""",
            "strategy.type = 'grid' requires a [grid] section",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
side = "sell"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 8
quote_amount_per_level = "100"
max_active_buy_orders = 3
max_inventory_levels = 4
""",
            "grid side must be 'buy'",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
order_type = "market"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 8
quote_amount_per_level = "100"
max_active_buy_orders = 3
max_inventory_levels = 4
""",
            "grid order_type must be 'limit'",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "2200"
price_band_high = "1800"
grid_levels = 8
quote_amount_per_level = "100"
max_active_buy_orders = 3
max_inventory_levels = 4
""",
            "price_band_low must be less than price_band_high",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 1
quote_amount_per_level = "100"
max_active_buy_orders = 1
max_inventory_levels = 1
""",
            "grid_levels must be at least 2",
        ),
        (
            """
[credentials]
environment = "prod"
api_key = "key"
private_key = "pk"
trading_account_id = "123"

[grid]
symbol = "ETH_USDT_Perp"
price_band_low = "1800"
price_band_high = "2200"
grid_levels = 6
spacing_mode = "geometric"
quote_amount_per_level = "100"
max_active_buy_orders = 2
max_inventory_levels = 2
""",
            "grid spacing_mode must be 'arithmetic' in v1",
        ),
    ],
)
def test_load_config_rejects_invalid_strategy_shapes(raw_text, message) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        load_config_text(raw_text, resolve_state_paths=False)
