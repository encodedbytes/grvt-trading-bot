from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .config import DcaSettings
from .exchange import AccountFill, PositionSnapshot
from .recovery_common import PRICE_TOLERANCE_RATIO, QTY_TOLERANCE_RATIO, within_tolerance
from .state import ActiveCycleState
from .strategy import current_quote_amount


UTC = timezone.utc
QUOTE_TOLERANCE_RATIO = Decimal("0.25")


@dataclass(frozen=True)
class GroupedFill:
    event_time: int
    symbol: str
    side: str
    size: Decimal
    average_price: Decimal
    order_id: str | None
    client_order_id: str | None
    fill_count: int


@dataclass(frozen=True)
class ReconstructionResult:
    succeeded: bool
    message: str
    cycle: ActiveCycleState | None = None


def _group_fills(fills: list[AccountFill]) -> list[GroupedFill]:
    grouped: dict[tuple[str, str], list[AccountFill]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for fill in sorted(fills, key=lambda item: item.event_time, reverse=True):
        key = (fill.order_id or "", fill.client_order_id or "")
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(fill)

    result: list[GroupedFill] = []
    for key in ordered_keys:
        bucket = grouped[key]
        side = bucket[0].side
        if any(fill.side != side for fill in bucket):
            return []
        total_size = sum(fill.size for fill in bucket)
        total_cost = sum(fill.size * fill.price for fill in bucket)
        average_price = total_cost / total_size if total_size > 0 else Decimal("0")
        result.append(
            GroupedFill(
                event_time=max(fill.event_time for fill in bucket),
                symbol=bucket[0].symbol,
                side=side,
                size=total_size,
                average_price=average_price,
                order_id=bucket[0].order_id,
                client_order_id=bucket[0].client_order_id,
                fill_count=len(bucket),
            )
        )
    return result


def _event_time_to_iso(event_time: int) -> str:
    seconds = event_time / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def _quote_matches_expected(actual_quote: Decimal, expected_quote: Decimal) -> bool:
    tolerance = max(Decimal("0.01"), expected_quote * QUOTE_TOLERANCE_RATIO)
    return abs(actual_quote - expected_quote) <= tolerance


def reconstruct_active_cycle(
    *,
    settings: DcaSettings,
    position: PositionSnapshot,
    fills: list[AccountFill],
) -> ReconstructionResult:
    grouped_fills = _group_fills([fill for fill in fills if fill.symbol == position.symbol])
    if not grouped_fills:
        return ReconstructionResult(
            succeeded=False,
            message="No grouped fills were available for reconstruction.",
        )

    candidates: list[GroupedFill] = []
    accumulated_size = Decimal("0")
    max_entry_count = settings.max_safety_orders + 1
    for grouped in grouped_fills:
        if grouped.side != position.side:
            if accumulated_size > 0:
                return ReconstructionResult(
                    succeeded=False,
                    message=(
                        "Encountered an opposite-side fill before the live position size "
                        "was reconciled."
                    ),
                )
            return ReconstructionResult(
                succeeded=False,
                message="Most recent fill side does not match the live position side.",
            )
        candidates.append(grouped)
        accumulated_size += grouped.size
        if len(candidates) > max_entry_count:
            return ReconstructionResult(
                succeeded=False,
                message=(
                    "More entry fills were required than the configured initial-plus-safety "
                    "ladder allows."
                ),
            )
        if within_tolerance(accumulated_size, position.size, QTY_TOLERANCE_RATIO):
            break
        if accumulated_size > position.size and not within_tolerance(
            accumulated_size, position.size, QTY_TOLERANCE_RATIO
        ):
            return ReconstructionResult(
                succeeded=False,
                message="Recent entry fills overshot the live position size.",
            )

    if not within_tolerance(accumulated_size, position.size, QTY_TOLERANCE_RATIO):
        return ReconstructionResult(
            succeeded=False,
            message="Recent entry fills did not reconcile to the live position size.",
        )

    ordered_entries = list(reversed(candidates))
    for index, entry_fill in enumerate(ordered_entries):
        expected_quote = current_quote_amount(settings, index)
        actual_quote = entry_fill.size * entry_fill.average_price
        if not _quote_matches_expected(actual_quote, expected_quote):
            return ReconstructionResult(
                succeeded=False,
                message=(
                    "Recent entry fill notional did not match the configured DCA ladder: "
                    f"index={index} actual_quote={actual_quote} expected_quote={expected_quote}"
                ),
            )

    total_quantity = sum(fill.size for fill in ordered_entries)
    total_cost = sum(fill.size * fill.average_price for fill in ordered_entries)
    average_entry_price = total_cost / total_quantity
    if not within_tolerance(
        average_entry_price,
        position.average_entry_price,
        PRICE_TOLERANCE_RATIO,
    ):
        return ReconstructionResult(
            succeeded=False,
            message=(
                "Reconstructed average entry price did not match the live position average: "
                f"reconstructed_avg_entry={average_entry_price} "
                f"position_avg_entry={position.average_entry_price}"
            ),
        )

    oldest_fill = ordered_entries[0]
    newest_fill = ordered_entries[-1]
    cycle = ActiveCycleState(
        symbol=position.symbol,
        side=position.side,
        started_at=_event_time_to_iso(oldest_fill.event_time),
        total_quantity=total_quantity,
        total_cost=total_cost,
        average_entry_price=average_entry_price,
        leverage=position.leverage,
        margin_type=position.margin_type,
        completed_safety_orders=max(0, len(ordered_entries) - 1),
        last_order_id=newest_fill.order_id,
        last_client_order_id=newest_fill.client_order_id,
    )
    return ReconstructionResult(
        succeeded=True,
        message=(
            "Reconstructed active cycle from exchange fills. "
            f"entry_count={len(ordered_entries)} completed_safety_orders={cycle.completed_safety_orders}"
        ),
        cycle=cycle,
    )
