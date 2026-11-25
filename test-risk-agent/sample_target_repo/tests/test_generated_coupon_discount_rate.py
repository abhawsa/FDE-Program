from billing.discounts import coupon_discount_rate


def test_coupon_discount_rate_known_codes():
    assert coupon_discount_rate("SAVE10") == 0.10
    assert coupon_discount_rate("VIP30") == 0.30


def test_coupon_discount_rate_is_case_insensitive():
    assert coupon_discount_rate("save10") == 0.10


def test_coupon_discount_rate_unknown_code_returns_zero():
    assert coupon_discount_rate("NOTREAL") == 0.0


def test_coupon_discount_rate_none_returns_zero():
    assert coupon_discount_rate(None) == 0.0
