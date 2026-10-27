"""Property tests of `domain/money.py` (hypothesis): what holds for every amount, not only
for the hand-picked ones of `test_money.py`.

- `round_ratio` is `round_half_away` of the exact `Fraction`; it is never farther than
  half a unit from the exact value, and an exact half goes away from zero.
- `to_minor` / `from_minor` / `format_minor` go round: stored minor units come back as
  the same int through the exact Decimal and through the text a user reads.
- A float is never accepted, whatever its value; more than two decimals is an error.
- `portal_minor` rounds the portal's four decimals half up, to the same as the Decimal
  arithmetic.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from modern_gl.domain.money import (
    format_minor,
    from_minor,
    portal_minor,
    read_decimal,
    round_half_away,
    round_ratio,
    to_minor,
)

MINOR = st.integers(min_value=-(10**15), max_value=10**15)
NUMERATOR = st.integers(min_value=-(10**12), max_value=10**12)
DENOMINATOR = st.integers(min_value=1, max_value=10**9)


@given(NUMERATOR, DENOMINATOR)
def test_round_ratio_is_the_exact_fraction_rounded(numerator: int, denominator: int) -> None:
    exact = Fraction(numerator, denominator)
    result = round_ratio(numerator, denominator)
    assert result == round_half_away(exact)
    assert round_ratio(-numerator, -denominator) == result  # a negative denominator too
    assert abs(Fraction(result) - exact) <= Fraction(1, 2)
    if abs(exact - int(exact)) == Fraction(1, 2):  # a half: away from zero
        assert abs(result) == abs(int(exact)) + 1
        assert (result >= 0) == (exact >= 0)


@given(NUMERATOR, DENOMINATOR)
def test_round_ratio_is_odd_and_monotonic(numerator: int, denominator: int) -> None:
    assert round_ratio(-numerator, denominator) == -round_ratio(numerator, denominator)
    assert round_ratio(numerator, denominator) <= round_ratio(numerator + denominator, denominator)
    assert round_ratio(numerator * denominator, denominator) == numerator


@given(MINOR)
def test_minor_units_go_round_through_decimal_and_text(minor: int) -> None:
    exact = from_minor(minor)
    assert to_minor(exact) == minor
    assert to_minor(str(exact)) == minor
    text = format_minor(minor)
    assert to_minor(text) == minor
    assert text.endswith(f".{abs(minor) % 100:02d}")
    assert text.startswith("-") == (minor < 0)
    assert to_minor(text.replace(".", ",")) == minor  # a comma is read the same


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_a_float_is_never_an_amount(value: float) -> None:
    with pytest.raises(TypeError):
        to_minor(value)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        read_decimal(value)  # type: ignore[arg-type]


@given(MINOR, st.integers(min_value=1, max_value=9))
def test_a_third_decimal_is_refused_not_rounded(minor: int, digit: int) -> None:
    text = f"{from_minor(minor)}{digit}"
    with pytest.raises(ValueError, match=re.escape(text)):
        to_minor(text)


@given(st.integers(min_value=-(10**13), max_value=10**13), st.integers(min_value=0, max_value=9999))
def test_portal_amounts_round_half_up_to_minor_units(whole: int, fraction: int) -> None:
    text = f"{whole}.{fraction:04d}" if whole >= 0 else f"-{abs(whole)}.{fraction:04d}"
    expected = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert portal_minor(text) == to_minor(expected)
    assert portal_minor(text) == -portal_minor(text.removeprefix("-") if whole < 0 else f"-{text}")
