"""Billing calculation utilities for the demo storefront.

Synthetic sample module - part of the seed repository used to demonstrate
the AI Test Coverage & Regression Risk Agent. Contains no real business data.
"""


def round_currency(amount: float) -> float:
    """Round a monetary amount to 2 decimal places, tolerant of float noise."""
    return round(amount + 1e-9, 2)


def apply_tax(subtotal: float, tax_rate: float) -> float:
    if tax_rate < 0:
        raise ValueError("tax_rate cannot be negative")
    return round_currency(subtotal * (1 + tax_rate))


def calculate_total(unit_price: float, quantity: int, tax_rate: float = 0.0) -> float:
    if quantity < 0:
        raise ValueError("quantity cannot be negative")
    subtotal = unit_price * quantity
    if subtotal < 0:
        subtotal = 0.0
    return apply_tax(subtotal, tax_rate)
