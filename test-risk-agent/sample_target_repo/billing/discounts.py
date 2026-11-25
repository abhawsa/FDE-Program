"""Discount rules for the demo storefront."""

from .calculator import round_currency

_VALID_COUPONS = {"SAVE10": 0.10, "SAVE20": 0.20, "VIP30": 0.30}
_MAX_COMBINED_DISCOUNT_RATE = 0.50


def bulk_discount_rate(quantity: int) -> float:
    if quantity >= 100:
        return 0.15
    if quantity >= 50:
        return 0.10
    if quantity >= 10:
        return 0.05
    return 0.0


def coupon_discount_rate(coupon_code):
    if not coupon_code:
        return 0.0
    return _VALID_COUPONS.get(coupon_code, 0.0)


def apply_discount(subtotal: float, quantity: int, coupon_code=None, *, stack=True) -> float:
    if subtotal < 0:
        raise ValueError("subtotal cannot be negative")
    bulk_rate = bulk_discount_rate(quantity)
    coupon_rate = coupon_discount_rate(coupon_code)
    if stack:
        rate = min(bulk_rate + coupon_rate, _MAX_COMBINED_DISCOUNT_RATE)
    else:
        rate = max(bulk_rate, coupon_rate)
    return round_currency(subtotal * (1 - rate))
