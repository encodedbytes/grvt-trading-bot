from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class GrvtCredentials:
    api_key: str
    private_key: str
    trading_account_id: str
    environment: str = "testnet"


@dataclass(frozen=True)
class DcaSettings:
    symbol: str
    side: str
    initial_quote_amount: Decimal
    safety_order_quote_amount: Decimal
    max_safety_orders: int
    price_deviation_percent: Decimal
    take_profit_percent: Decimal
    order_type: str = "market"
    limit_price_offset_percent: Decimal = Decimal("0")
    initial_leverage: Decimal | None = None
    margin_type: str | None = None
    safety_order_step_scale: Decimal = Decimal("1")
    safety_order_volume_scale: Decimal = Decimal("1")
    stop_loss_percent: Decimal | None = None
    max_cycles: int | None = None
    state_file: Path = Path(".gravity-dca-state.json")


@dataclass(frozen=True)
class RuntimeSettings:
    dry_run: bool = True
    poll_seconds: int = 30
    order_fill_timeout_seconds: int = 10
    order_fill_poll_seconds: int = 1
    limit_ttl_seconds: int = 30
    log_level: str = "INFO"


@dataclass(frozen=True)
class AppConfig:
    credentials: GrvtCredentials
    dca: DcaSettings
    runtime: RuntimeSettings


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _resolve_state_file(raw_path: object, config_path: str | Path) -> Path:
    path = Path(str(raw_path))
    if not path.is_absolute():
        return path
    if path.exists():
        return path
    if path.parts and path.parts[1:2] == ("state",):
        config_dir = Path(config_path).resolve().parent
        host_state_path = config_dir / "state" / Path(*path.parts[2:])
        return host_state_path
    return path


def load_config(path: str | Path) -> AppConfig:
    raw = tomllib.loads(Path(path).read_text())

    credentials = raw["credentials"]
    dca = raw["dca"]
    runtime = raw.get("runtime", {})

    return AppConfig(
        credentials=GrvtCredentials(
            api_key=str(credentials["api_key"]),
            private_key=str(credentials["private_key"]),
            trading_account_id=str(credentials["trading_account_id"]),
            environment=str(credentials.get("environment", "testnet")).lower(),
        ),
        dca=DcaSettings(
            symbol=str(dca["symbol"]),
            side=str(dca.get("side", "buy")).lower(),
            initial_quote_amount=Decimal(str(dca["initial_quote_amount"])),
            safety_order_quote_amount=Decimal(str(dca["safety_order_quote_amount"])),
            order_type=str(dca.get("order_type", "market")).strip().lower(),
            limit_price_offset_percent=Decimal(
                str(dca.get("limit_price_offset_percent", "0"))
            ),
            initial_leverage=_optional_decimal(dca.get("initial_leverage")),
            margin_type=(
                str(dca["margin_type"]).strip()
                if dca.get("margin_type") is not None
                else None
            ),
            max_safety_orders=int(dca["max_safety_orders"]),
            price_deviation_percent=Decimal(str(dca["price_deviation_percent"])),
            take_profit_percent=Decimal(str(dca["take_profit_percent"])),
            safety_order_step_scale=Decimal(str(dca.get("safety_order_step_scale", "1"))),
            safety_order_volume_scale=Decimal(str(dca.get("safety_order_volume_scale", "1"))),
            stop_loss_percent=_optional_decimal(dca.get("stop_loss_percent")),
            max_cycles=int(dca["max_cycles"]) if dca.get("max_cycles") is not None else None,
            state_file=_resolve_state_file(dca.get("state_file", ".gravity-dca-state.json"), path),
        ),
        runtime=RuntimeSettings(
            dry_run=bool(runtime.get("dry_run", True)),
            poll_seconds=int(runtime.get("poll_seconds", 30)),
            order_fill_timeout_seconds=int(runtime.get("order_fill_timeout_seconds", 10)),
            order_fill_poll_seconds=int(runtime.get("order_fill_poll_seconds", 1)),
            limit_ttl_seconds=int(runtime.get("limit_ttl_seconds", 30)),
            log_level=str(runtime.get("log_level", "INFO")).upper(),
        ),
    )
