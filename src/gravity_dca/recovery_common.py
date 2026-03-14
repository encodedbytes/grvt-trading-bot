from __future__ import annotations

from decimal import Decimal


QTY_TOLERANCE_RATIO = Decimal("0.0001")
PRICE_TOLERANCE_RATIO = Decimal("0.0001")
MIN_TOLERANCE = Decimal("0.00000001")


def within_tolerance(left: Decimal, right: Decimal, ratio: Decimal) -> bool:
    baseline = max(abs(left), abs(right), Decimal("1"))
    tolerance = max(MIN_TOLERANCE, baseline * ratio)
    return abs(left - right) <= tolerance
