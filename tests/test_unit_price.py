"""Price of a unit and amount of a line: one rounding everywhere (half away from zero)."""

from modern_gl.application.inventory import QUANTITY_FACTOR, line_amount, unit_price


def test_price_of_a_unit():
    assert unit_price(1000, 3 * QUANTITY_FACTOR) == 333  # 10.00 / 3 = 3.333…
    assert unit_price(5, 2 * QUANTITY_FACTOR) == 3  # 0.025 → 0.03
    assert unit_price(-5, 2 * QUANTITY_FACTOR) == -3  # a negative balance: the same rule
    assert unit_price(1000, 0) is None


def test_amount_of_a_line():
    assert line_amount(333, 3 * QUANTITY_FACTOR) == 999
    assert line_amount(1001, QUANTITY_FACTOR // 2) == 501  # 10.01 × 0.5 = 5.005 → 5.01
