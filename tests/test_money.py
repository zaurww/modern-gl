from decimal import Decimal

import pytest

from modern_gl.domain.money import format_minor, to_minor


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
