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
    bot_api_port: int = 8787
    order_fill_timeout_seconds: int = 10
    order_fill_poll_seconds: int = 1
    limit_ttl_seconds: int = 30
    private_auth_retry_attempts: int = 3
    private_auth_retry_backoff_seconds: int = 2
    log_level: str = "INFO"


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    send_startup_summary: bool = True
    notify_position_config_changes: bool = True
    error_notification_cooldown_seconds: int = 300


@dataclass(frozen=True)
class AppConfig:
    credentials: GrvtCredentials
    dca: DcaSettings
    runtime: RuntimeSettings
    telegram: TelegramSettings


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
    if path.parent.exists():
        return path
    if path.parts and path.parts[1:2] == ("state",):
        config_dir = Path(config_path).resolve().parent
        relative_state_path = Path("state") / Path(*path.parts[2:])
        for candidate_dir in (config_dir, *config_dir.parents):
            candidate = candidate_dir / relative_state_path
            if candidate.parent.exists():
                return candidate
        return config_dir / relative_state_path
    return path


def _build_app_config(
    raw: dict,
    *,
    config_path: str | Path,
    resolve_state_paths: bool,
) -> AppConfig:
    credentials = raw["credentials"]
    dca = raw["dca"]
    runtime = raw.get("runtime", {})
    telegram = raw.get("telegram", {})
    state_file = (
        _resolve_state_file(dca.get("state_file", ".gravity-dca-state.json"), config_path)
        if resolve_state_paths
        else Path(str(dca.get("state_file", ".gravity-dca-state.json")))
    )

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
            state_file=state_file,
        ),
        runtime=RuntimeSettings(
            dry_run=bool(runtime.get("dry_run", True)),
            poll_seconds=int(runtime.get("poll_seconds", 30)),
            bot_api_port=int(runtime.get("bot_api_port", 8787)),
            order_fill_timeout_seconds=int(runtime.get("order_fill_timeout_seconds", 10)),
            order_fill_poll_seconds=int(runtime.get("order_fill_poll_seconds", 1)),
            limit_ttl_seconds=int(runtime.get("limit_ttl_seconds", 30)),
            private_auth_retry_attempts=int(runtime.get("private_auth_retry_attempts", 3)),
            private_auth_retry_backoff_seconds=int(
                runtime.get("private_auth_retry_backoff_seconds", 2)
            ),
            log_level=str(runtime.get("log_level", "INFO")).upper(),
        ),
        telegram=TelegramSettings(
            enabled=bool(telegram.get("enabled", False)),
            bot_token=(
                str(telegram["bot_token"]).strip()
                if telegram.get("bot_token") is not None
                else None
            ),
            chat_id=(
                str(telegram["chat_id"]).strip()
                if telegram.get("chat_id") is not None
                else None
            ),
            send_startup_summary=bool(telegram.get("send_startup_summary", True)),
            notify_position_config_changes=bool(
                telegram.get("notify_position_config_changes", True)
            ),
            error_notification_cooldown_seconds=int(
                telegram.get("error_notification_cooldown_seconds", 300)
            ),
        ),
    )


def load_config_text(
    raw_text: str,
    *,
    config_path: str | Path = "<memory>",
    resolve_state_paths: bool = True,
) -> AppConfig:
    raw = tomllib.loads(raw_text)
    return _build_app_config(
        raw,
        config_path=config_path,
        resolve_state_paths=resolve_state_paths,
    )


def load_config(path: str | Path) -> AppConfig:
    return load_config_text(Path(path).read_text(), config_path=path)
