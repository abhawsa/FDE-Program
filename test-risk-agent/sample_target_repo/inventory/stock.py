"""Inventory utilities for the demo storefront.

Synthetic sample module. This file is the "stable" counterpart to
billing/discounts.py in the demo: low complexity, rarely touched, so even
though it also starts at 0% test coverage, it should rank far below the
discount logic once change-frequency is factored in.
"""


def is_low_stock(current_quantity: int, reorder_threshold: int) -> bool:
    return current_quantity <= reorder_threshold


def reorder_point(average_daily_sales: float, lead_time_days: int, safety_stock: int = 0) -> int:
    if average_daily_sales < 0 or lead_time_days < 0:
        raise ValueError("average_daily_sales and lead_time_days must be non-negative")
    return int(round(average_daily_sales * lead_time_days)) + safety_stock
