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
            max_safety_orders=int(dca["max_safety_orders"]),
            price_deviation_percent=Decimal(str(dca["price_deviation_percent"])),
            take_profit_percent=Decimal(str(dca["take_profit_percent"])),
            safety_order_step_scale=Decimal(str(dca.get("safety_order_step_scale", "1"))),
            safety_order_volume_scale=Decimal(str(dca.get("safety_order_volume_scale", "1"))),
            stop_loss_percent=_optional_decimal(dca.get("stop_loss_percent")),
            max_cycles=int(dca["max_cycles"]) if dca.get("max_cycles") is not None else None,
            state_file=Path(str(dca.get("state_file", ".gravity-dca-state.json"))),
        ),
        runtime=RuntimeSettings(
            dry_run=bool(runtime.get("dry_run", True)),
            poll_seconds=int(runtime.get("poll_seconds", 30)),
            order_fill_timeout_seconds=int(runtime.get("order_fill_timeout_seconds", 10)),
            order_fill_poll_seconds=int(runtime.get("order_fill_poll_seconds", 1)),
            log_level=str(runtime.get("log_level", "INFO")).upper(),
        ),
    )
