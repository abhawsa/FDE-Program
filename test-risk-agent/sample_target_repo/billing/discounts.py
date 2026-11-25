"""Discount rules for the demo storefront."""

_VALID_COUPONS = {"SAVE10": 0.10, "SAVE20": 0.20}


def bulk_discount_rate(quantity: int) -> float:
    if quantity >= 50:
        return 0.10
    if quantity >= 10:
        return 0.05
    return 0.0


def coupon_discount_rate(coupon_code):
    if not coupon_code:
        return 0.0
    return _VALID_COUPONS.get(coupon_code, 0.0)


def apply_discount(subtotal: float, quantity: int, coupon_code=None) -> float:
    rate = bulk_discount_rate(quantity) + coupon_discount_rate(coupon_code)
    return round(subtotal * (1 - rate), 2)
