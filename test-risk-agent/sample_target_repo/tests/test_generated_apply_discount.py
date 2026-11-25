"""Covers apply_discount's stacking, cap, and non-stacking behavior."""
import pytest

from billing.discounts import apply_discount


def test_apply_discount_stacks_bulk_and_coupon_by_default():
    assert apply_discount(100.0, 60, "SAVE20") == 70.0


def test_apply_discount_stacks_top_tier_without_exceeding_cap():
    assert apply_discount(100.0, 100, "VIP30") == 55.0


def test_apply_discount_non_stacking_uses_larger_rate_only():
    assert apply_discount(100.0, 60, "SAVE20", stack=False) == 80.0


def test_apply_discount_rejects_negative_subtotal():
    with pytest.raises(ValueError) as excinfo:
        apply_discount(-1.0, 10)
    assert "negative" in str(excinfo.value)
