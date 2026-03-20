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
class MomentumSettings:
    symbol: str
    side: str
    quote_amount: Decimal
    timeframe: str
    ema_fast_period: int
    ema_slow_period: int
    breakout_lookback: int
    adx_period: int
    min_adx: Decimal
    atr_period: int
    min_atr_percent: Decimal
    stop_atr_multiple: Decimal
    trailing_atr_multiple: Decimal
    order_type: str = "market"
    limit_price_offset_percent: Decimal = Decimal("0")
    initial_leverage: Decimal | None = None
    margin_type: str | None = None
    max_cycles: int | None = None
    use_trend_failure_exit: bool = True
    take_profit_percent: Decimal | None = None
    state_file: Path = Path(".gravity-momentum-state.json")


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
    dca: DcaSettings | None
    runtime: RuntimeSettings
    telegram: TelegramSettings
    strategy_type: str = "dca"
    momentum: MomentumSettings | None = None


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
    strategy = raw.get("strategy", {})
    dca = raw.get("dca") or strategy.get("dca")
    momentum = raw.get("momentum") or strategy.get("momentum")
    runtime = raw.get("runtime", {})
    telegram = raw.get("telegram", {})
    explicit_strategy_type = (
        str(strategy.get("type", "")).strip().lower() if strategy.get("type") is not None else ""
    )
    has_dca = dca is not None
    has_momentum = momentum is not None

    if not has_dca and not has_momentum:
        raise ValueError("config must define either a [dca] or [momentum] section")
    if has_dca and has_momentum:
        raise ValueError("config cannot define both [dca] and [momentum] sections")

    if explicit_strategy_type:
        if explicit_strategy_type not in {"dca", "momentum"}:
            raise ValueError(f"unsupported strategy.type: {explicit_strategy_type}")
        if explicit_strategy_type == "dca" and not has_dca:
            raise ValueError("strategy.type = 'dca' requires a [dca] section")
        if explicit_strategy_type == "momentum" and not has_momentum:
            raise ValueError("strategy.type = 'momentum' requires a [momentum] section")
        strategy_type = explicit_strategy_type
    else:
        strategy_type = "momentum" if has_momentum else "dca"

    dca_settings = None
    if dca is not None:
        dca_state_file = (
            _resolve_state_file(dca.get("state_file", ".gravity-dca-state.json"), config_path)
            if resolve_state_paths
            else Path(str(dca.get("state_file", ".gravity-dca-state.json")))
        )
        dca_settings = DcaSettings(
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
            state_file=dca_state_file,
        )

    momentum_settings = None
    if momentum is not None:
        momentum_side = str(momentum.get("side", "buy")).lower()
        if momentum_side != "buy":
            raise ValueError("momentum side must be 'buy'")
        momentum_state_file = (
            _resolve_state_file(momentum.get("state_file", ".gravity-momentum-state.json"), config_path)
            if resolve_state_paths
            else Path(str(momentum.get("state_file", ".gravity-momentum-state.json")))
        )
        momentum_settings = MomentumSettings(
            symbol=str(momentum["symbol"]),
            side=momentum_side,
            quote_amount=Decimal(str(momentum["quote_amount"])),
            order_type=str(momentum.get("order_type", "market")).strip().lower(),
            limit_price_offset_percent=Decimal(
                str(momentum.get("limit_price_offset_percent", "0"))
            ),
            initial_leverage=_optional_decimal(momentum.get("initial_leverage")),
            margin_type=(
                str(momentum["margin_type"]).strip()
                if momentum.get("margin_type") is not None
                else None
            ),
            max_cycles=(
                int(momentum["max_cycles"]) if momentum.get("max_cycles") is not None else None
            ),
            timeframe=str(momentum["timeframe"]),
            ema_fast_period=int(momentum["ema_fast_period"]),
            ema_slow_period=int(momentum["ema_slow_period"]),
            breakout_lookback=int(momentum["breakout_lookback"]),
            adx_period=int(momentum["adx_period"]),
            min_adx=Decimal(str(momentum["min_adx"])),
            atr_period=int(momentum["atr_period"]),
            min_atr_percent=Decimal(str(momentum["min_atr_percent"])),
            stop_atr_multiple=Decimal(str(momentum["stop_atr_multiple"])),
            trailing_atr_multiple=Decimal(str(momentum["trailing_atr_multiple"])),
            use_trend_failure_exit=bool(momentum.get("use_trend_failure_exit", True)),
            take_profit_percent=_optional_decimal(momentum.get("take_profit_percent")),
            state_file=momentum_state_file,
        )

    return AppConfig(
        credentials=GrvtCredentials(
            api_key=str(credentials["api_key"]),
            private_key=str(credentials["private_key"]),
            trading_account_id=str(credentials["trading_account_id"]),
            environment=str(credentials.get("environment", "testnet")).lower(),
        ),
        dca=dca_settings,
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
        strategy_type=strategy_type,
        momentum=momentum_settings,
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
