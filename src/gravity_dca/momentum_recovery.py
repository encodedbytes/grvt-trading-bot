from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .config import MomentumSettings
from .exchange import AccountFill, PositionSnapshot
from .grvt_models import Candle
from .momentum_state import ActiveMomentumState, MomentumBotState
from .momentum_strategy import build_indicator_snapshot, next_trailing_stop_price
from .recovery_common import PRICE_TOLERANCE_RATIO, QTY_TOLERANCE_RATIO, within_tolerance


@dataclass(frozen=True)
class MomentumRecoveryDecision:
    action: str
    message: str
    recovered_position: ActiveMomentumState | None = None
    reconstruction_attempted: bool = False
    reconstruction_succeeded: bool = False
    reconstruction_message: str | None = None


def _default_started_at(when: datetime, fill: AccountFill | None) -> str:
    if fill is None:
        return when.isoformat()
    return datetime.fromtimestamp(fill.event_time / 1_000_000_000, tz=when.tzinfo).isoformat()


def _latest_close(candles: list[Candle]) -> Decimal:
    if not candles:
        raise ValueError("Momentum recovery requires recent candles to recompute stops")
    return candles[-1].close


def _best_entry_fill(
    *,
    position: PositionSnapshot,
    fills: list[AccountFill] | None,
) -> AccountFill | None:
    if not fills:
        return None
    for fill in sorted(fills, key=lambda item: item.event_time, reverse=True):
        if fill.symbol != position.symbol:
            continue
        if fill.side != position.side:
            continue
        if within_tolerance(fill.size, position.size, QTY_TOLERANCE_RATIO):
            return fill
    return None


def _recover_position(
    *,
    settings: MomentumSettings,
    position: PositionSnapshot,
    candles: list[Candle],
    when: datetime,
    existing_position: ActiveMomentumState | None,
    entry_fill: AccountFill | None,
) -> ActiveMomentumState:
    indicator_snapshot = build_indicator_snapshot(candles, settings)
    if indicator_snapshot is None:
        raise ValueError("Momentum recovery requires enough candle history to compute ATR")
    highest_price = max(
        value
        for value in (
            existing_position.highest_price_since_entry if existing_position is not None else None,
            position.average_entry_price,
            indicator_snapshot.close_price,
        )
        if value is not None
    )
    initial_stop = (
        existing_position.initial_stop_price
        if existing_position is not None and existing_position.initial_stop_price is not None
        else position.average_entry_price - (indicator_snapshot.atr * settings.stop_atr_multiple)
    )
    trailing_stop = next_trailing_stop_price(
        ActiveMomentumState(
            symbol=position.symbol,
            side=position.side,
            started_at=(
                existing_position.started_at
                if existing_position is not None
                else _default_started_at(when, entry_fill)
            ),
            total_quantity=position.size,
            total_cost=position.size * position.average_entry_price,
            average_entry_price=position.average_entry_price,
            leverage=position.leverage,
            margin_type=position.margin_type,
            last_order_id=(
                existing_position.last_order_id if existing_position is not None else entry_fill.order_id if entry_fill is not None else None
            ),
            last_client_order_id=(
                existing_position.last_client_order_id
                if existing_position is not None
                else entry_fill.client_order_id if entry_fill is not None else None
            ),
            highest_price_since_entry=highest_price,
            initial_stop_price=initial_stop,
            trailing_stop_price=(
                existing_position.trailing_stop_price if existing_position is not None else None
            ),
            breakout_level=(
                existing_position.breakout_level
                if existing_position is not None
                else indicator_snapshot.breakout_level
            ),
            timeframe=settings.timeframe,
        ),
        indicator_snapshot.atr,
        settings,
    )
    return ActiveMomentumState(
        symbol=position.symbol,
        side=position.side,
        started_at=(
            existing_position.started_at
            if existing_position is not None
            else _default_started_at(when, entry_fill)
        ),
        total_quantity=position.size,
        total_cost=position.size * position.average_entry_price,
        average_entry_price=position.average_entry_price,
        leverage=position.leverage,
        margin_type=position.margin_type,
        last_order_id=(
            existing_position.last_order_id if existing_position is not None else entry_fill.order_id if entry_fill is not None else None
        ),
        last_client_order_id=(
            existing_position.last_client_order_id
            if existing_position is not None
            else entry_fill.client_order_id if entry_fill is not None else None
        ),
        highest_price_since_entry=highest_price,
        initial_stop_price=initial_stop,
        trailing_stop_price=trailing_stop,
        breakout_level=(
            existing_position.breakout_level if existing_position is not None else indicator_snapshot.breakout_level
        ),
        timeframe=settings.timeframe,
    )


def reconcile_momentum_state(
    *,
    state: MomentumBotState,
    settings: MomentumSettings,
    symbol: str,
    exchange_position: PositionSnapshot | None,
    exchange_fills: list[AccountFill] | None,
    candles: list[Candle],
    when: datetime,
) -> MomentumRecoveryDecision:
    local_position = state.active_position
    if local_position is not None and local_position.symbol != symbol:
        raise ValueError(
            "Local active momentum position symbol mismatch: "
            f"state_symbol={local_position.symbol} config_symbol={symbol}"
        )

    if local_position is None and exchange_position is None:
        return MomentumRecoveryDecision(
            action="no-op",
            message="No local active momentum position and no exchange position.",
        )

    if local_position is None and exchange_position is not None:
        if exchange_position.side != settings.side:
            raise ValueError(
                f"Exchange position side does not match momentum strategy side: "
                f"exchange_side={exchange_position.side} strategy_side={settings.side}"
            )
        entry_fill = _best_entry_fill(position=exchange_position, fills=exchange_fills)
        reconstruction_message = (
            "Recovered momentum position metadata from exchange fills."
            if entry_fill is not None
            else "Recovered momentum position from exchange position snapshot."
        )
        return MomentumRecoveryDecision(
            action="rebuild-from-exchange-history" if entry_fill is not None else "rebuild-from-exchange",
            message="Recovered active momentum position from exchange.",
            recovered_position=_recover_position(
                settings=settings,
                position=exchange_position,
                candles=candles,
                when=when,
                existing_position=None,
                entry_fill=entry_fill,
            ),
            reconstruction_attempted=exchange_fills is not None,
            reconstruction_succeeded=entry_fill is not None,
            reconstruction_message=reconstruction_message,
        )

    if local_position is not None and exchange_position is None:
        return MomentumRecoveryDecision(
            action="clear-stale-local",
            message="Cleared stale local momentum position because no exchange position exists.",
        )

    assert local_position is not None
    assert exchange_position is not None

    if local_position.side != exchange_position.side:
        raise ValueError(
            f"Local and exchange momentum sides do not match: local_side={local_position.side} "
            f"exchange_side={exchange_position.side}"
        )
    if not within_tolerance(local_position.total_quantity, exchange_position.size, QTY_TOLERANCE_RATIO):
        raise ValueError(
            f"Local and exchange momentum quantities do not match: "
            f"local_qty={local_position.total_quantity} exchange_qty={exchange_position.size}"
        )
    if not within_tolerance(
        local_position.average_entry_price,
        exchange_position.average_entry_price,
        PRICE_TOLERANCE_RATIO,
    ):
        raise ValueError(
            "Local and exchange momentum average entry prices do not match: "
            f"local_avg_entry={local_position.average_entry_price} "
            f"exchange_avg_entry={exchange_position.average_entry_price}"
        )

    entry_fill = _best_entry_fill(position=exchange_position, fills=exchange_fills)
    return MomentumRecoveryDecision(
        action="keep-local",
        message="Local and exchange momentum state match.",
        recovered_position=_recover_position(
            settings=settings,
            position=exchange_position,
            candles=candles,
            when=when,
            existing_position=local_position,
            entry_fill=entry_fill,
        ),
        reconstruction_attempted=exchange_fills is not None,
        reconstruction_succeeded=False,
        reconstruction_message=(
            "Refresh kept local momentum position and reused exchange-backed metadata."
            if entry_fill is not None
            else None
        ),
    )
