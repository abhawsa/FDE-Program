"""Existing (partial) test coverage for billing.calculator.

Deliberately incomplete: it covers the happy path and the tax-rate
validation error, but not calculate_total's negative-quantity branch - that
gap, combined with discounts.py having no tests at all, is what the risk
agent is meant to surface.
"""
import pytest

from billing.calculator import apply_tax, calculate_total, round_currency


def test_round_currency_rounds_to_two_decimals():
    assert round_currency(19.995) == 20.0


def test_apply_tax_adds_percentage():
    assert apply_tax(100.0, 0.08) == 108.0


def test_apply_tax_rejects_negative_rate():
    with pytest.raises(ValueError):
        apply_tax(100.0, -0.1)


def test_calculate_total_happy_path():
    assert calculate_total(10.0, 3, tax_rate=0.1) == 33.0
