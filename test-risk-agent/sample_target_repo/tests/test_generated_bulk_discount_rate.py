from billing.discounts import bulk_discount_rate


def test_bulk_discount_rate_tiers():
    assert bulk_discount_rate(5) == 0.0
    assert bulk_discount_rate(10) == 0.05
    assert bulk_discount_rate(50) == 0.10
    assert bulk_discount_rate(100) == 0.15
