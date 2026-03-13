from decimal import Decimal

from gravity_dca.config import load_config
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
