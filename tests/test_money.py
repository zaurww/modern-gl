from decimal import Decimal
from fractions import Fraction

import pytest

from modern_gl.application.common import pad_subconto
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor, round_half_away, round_ratio, to_minor


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234.56", 123456),
        ("1 234,5", 123450),
        (" 100", 10000),
        (7, 700),
        (Decimal("0.01"), 1),
        ("-3.10", -310),
        ("0", 0),
    ],
)
def test_to_minor(value, expected):
    assert to_minor(value) == expected


@pytest.mark.parametrize("value", ["1.005", "abc", "", "NaN", "Infinity"])
def test_to_minor_rejects(value):
    with pytest.raises(ValueError):
        to_minor(value)


@pytest.mark.parametrize("value", [1.5, True])
def test_to_minor_rejects_float_and_bool(value):
    with pytest.raises(TypeError):
        to_minor(value)


def test_format_minor():
    assert format_minor(123456789) == "1 234 567.89"
    assert format_minor(-5) == "-0.05"
    assert format_minor(0) == "0.00"


def test_round_half_away_from_zero():
    assert round_half_away(Fraction(5, 2)) == 3
    assert round_half_away(Fraction(-5, 2)) == -3
    assert round_half_away(Fraction(249, 100)) == 2
    assert round_half_away(Fraction(-251, 100)) == -3
    # 100.00 manat of stock at 3 units, 1 unit issued: 10000 / 3 = 3333.33 -> 3333 qəpik
    assert round_ratio(10_000 * 1, 3) == 3_333
    assert round_ratio(10_000 * 2, 3) == 6_667  # 6666.67 -> 6667
    assert round_ratio(1, 2) == 1


def test_pad_subconto():
    assert pad_subconto([7]) == (7, None, None)
    assert pad_subconto([]) == (None, None, None)
    with pytest.raises(ValidationError, match="строка 2: больше 3 субконто"):
        pad_subconto([1, 2, 3, 4], 2)
    with pytest.raises(ValidationError, match="больше 3 субконто"):
        pad_subconto([1, 2, 3, 4])
