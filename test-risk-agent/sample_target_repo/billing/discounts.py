"""Discount rules for the demo storefront."""


def bulk_discount_rate(quantity: int) -> float:
    if quantity >= 50:
        return 0.10
    if quantity >= 10:
        return 0.05
    return 0.0


def apply_discount(subtotal: float, quantity: int) -> float:
    rate = bulk_discount_rate(quantity)
    return round(subtotal * (1 - rate), 2)
