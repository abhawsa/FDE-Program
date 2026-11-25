"""Discount rules for the demo storefront.

Synthetic sample module. This file is intentionally the "risky" one in the
seed repo: in the project scenario, a module like this changed 12 times in
a quarter (promotions evolve almost every sprint) while its test coverage
lagged behind - exactly the kind of path a naive coverage-only sprint would
under-prioritize.
"""
from typing import Optional

from .calculator import round_currency

_VALID_COUPONS = {"SAVE10": 0.10, "SAVE20": 0.20, "VIP30": 0.30}
_MAX_COMBINED_DISCOUNT_RATE = 0.50


def coupon_discount_rate(coupon_code: Optional[str]) -> float:
    if not coupon_code:
        return 0.0
    code = coupon_code.strip().upper()
    return _VALID_COUPONS.get(code, 0.0)


def bulk_discount_rate(quantity: int) -> float:
    if quantity >= 100:
        return 0.15
    if quantity >= 50:
        return 0.10
    if quantity >= 10:
        return 0.05
    return 0.0


def apply_discount(
    subtotal: float,
    quantity: int,
    coupon_code: Optional[str] = None,
    *,
    stack: bool = True,
) -> float:
    """Applies bulk + coupon discounts to a subtotal.

    When `stack` is True, bulk and coupon discounts add together (capped at
    _MAX_COMBINED_DISCOUNT_RATE). When False, only the larger of the two
    applies. This stacking behavior is the part that changes most often as
    promotions are tuned, and the part most likely to regress silently.
    """
    if subtotal < 0:
        raise ValueError("subtotal cannot be negative")

    bulk_rate = bulk_discount_rate(quantity)
    coupon_rate = coupon_discount_rate(coupon_code)

    if stack:
        rate = min(bulk_rate + coupon_rate, _MAX_COMBINED_DISCOUNT_RATE)
    else:
        rate = max(bulk_rate, coupon_rate)

    discounted = subtotal * (1 - rate)
    return round_currency(discounted)
