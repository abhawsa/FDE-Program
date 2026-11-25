import pytest

from inventory.stock import reorder_point


def test_reorder_point_computes_expected_units_plus_safety_stock():
    assert reorder_point(10.0, 5, safety_stock=20) == 70


def test_reorder_point_rejects_negative_inputs():
    with pytest.raises(ValueError) as excinfo:
        reorder_point(-1.0, 5)
    assert "non-negative" in str(excinfo.value)
