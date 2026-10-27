"""Property tests of `application/inventory/amounts.py` (hypothesis): the allocations
keep every minor unit and every rounding is the one of `domain/money.py`.

- `allocate_minor`: the shares add up to the total exactly, none is negative, each is
  the exact proportional share rounded down or up (never more than one unit off), a
  zero weight gets nothing, and equal weights differ by at most one unit.
- `split_charges`: every charge is spread whole, and when the charges add up to the
  targets, every target comes out exact.
- `vat_of`, `unit_price`, `line_amount`: the rounding of `round_ratio`; one unit at a
  price is that price; a quantity goes round through its text.
- `positive_amount` / `nonnegative_amount` refuse what their names say.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from modern_gl.application.inventory.amounts import (
    allocate_minor,
    format_quantity,
    line_amount,
    nonnegative_amount,
    positive_amount,
    split_charges,
    to_quantity,
    unit_price,
    vat_of,
)
from modern_gl.application.inventory.model import QUANTITY_FACTOR, QUANTITY_SCALE, VAT_RATE_SCALE
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio

TOTAL = st.integers(min_value=1, max_value=10**12)
WEIGHT = st.integers(min_value=0, max_value=10**9)
WEIGHTS = st.lists(WEIGHT, min_size=1, max_size=12).filter(lambda ws: sum(ws) > 0)


def keyed(weights: list[int]) -> list[tuple[int, int]]:
    return list(enumerate(weights, start=1))


@given(TOTAL, WEIGHTS)
def test_allocation_keeps_every_minor_unit(total: int, weights: list[int]) -> None:
    shares = allocate_minor(total, keyed(weights))
    assert sum(shares.values()) == total
    assert all(share >= 0 for share in shares.values())
    denominator = sum(weights)
    for key, weight in keyed(weights):
        exact = Fraction(total * weight, denominator)
        assert abs(Fraction(shares[key]) - exact) < 1
        assert shares[key] in (exact.__floor__(), exact.__ceil__())
        if weight == 0:
            assert shares[key] == 0


@given(TOTAL, st.integers(min_value=1, max_value=12), st.integers(min_value=1, max_value=10**6))
def test_equal_weights_differ_by_at_most_one_unit(total: int, count: int, weight: int) -> None:
    shares = allocate_minor(total, keyed([weight] * count))
    assert sum(shares.values()) == total
    assert max(shares.values()) - min(shares.values()) <= 1


@given(TOTAL, WEIGHTS)
def test_allocation_is_deterministic(total: int, weights: list[int]) -> None:
    assert allocate_minor(total, keyed(weights)) == allocate_minor(total, keyed(weights))


@given(st.integers(max_value=0), WEIGHTS)
def test_nothing_to_allocate_is_an_error(total: int, weights: list[int]) -> None:
    with pytest.raises(ValidationError):
        allocate_minor(total, keyed(weights))


@given(TOTAL, st.lists(st.just(0), min_size=1, max_size=8))
def test_a_zero_base_is_an_error(total: int, weights: list[int]) -> None:
    with pytest.raises(ValidationError):
        allocate_minor(total, keyed(weights))


@given(
    st.lists(st.integers(min_value=1, max_value=10**8), min_size=1, max_size=6),
    st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=6),
)
def test_charges_split_over_targets_come_out_exact(charges: list[int], parts: list[int]) -> None:
    """The targets take the charges' total in the proportion `parts`: every charge is
    spread whole and every target gets exactly what it can take."""
    total = sum(charges)
    targets = allocate_minor(total, keyed(parts))
    assume(all(targets.values()))
    shares = split_charges(keyed(charges), targets)
    assert all(share > 0 for share in shares.values())
    for charge_id, amount in keyed(charges):
        assert sum(s for (c, _), s in shares.items() if c == charge_id) == amount
    for key, capacity in targets.items():
        assert sum(s for (_, t), s in shares.items() if t == key) == capacity


@given(st.integers(min_value=0, max_value=10**11), st.integers(min_value=0, max_value=10**5))
def test_vat_is_the_rounded_ratio(amount: int, rate: int) -> None:
    assert vat_of(amount, rate) == (round_ratio(amount * rate, VAT_RATE_SCALE) if rate else 0)
    assert vat_of(amount, None) == 0
    assert vat_of(amount, rate) >= 0


@given(st.integers(min_value=0, max_value=10**11), st.integers(min_value=1, max_value=10**10))
def test_unit_price_and_line_amount_round_like_money(amount: int, quantity: int) -> None:
    price = unit_price(amount, quantity)
    assert price == round_ratio(amount * QUANTITY_FACTOR, quantity)
    assert unit_price(amount, 0) is None
    assert line_amount(price or 0, QUANTITY_FACTOR) == price
    assert line_amount(price or 0, quantity) == round_ratio(
        (price or 0) * quantity, QUANTITY_FACTOR
    )


@given(st.integers(min_value=0, max_value=10**12))
def test_a_quantity_goes_round_through_its_text(quantity: int) -> None:
    text = format_quantity(quantity, QUANTITY_SCALE)
    assert to_quantity(text) == quantity
    assert "." not in text or not text.endswith(("0", "."))  # no insignificant zeroes


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_a_float_is_never_a_quantity(value: float) -> None:
    with pytest.raises(TypeError):
        to_quantity(value)  # type: ignore[arg-type]


@given(st.integers(min_value=-(10**9), max_value=0))
def test_a_positive_amount_refuses_zero_and_less(amount: int) -> None:
    with pytest.raises(ValidationError):
        positive_amount(amount, 1)
    if amount < 0:
        with pytest.raises(ValidationError):
            nonnegative_amount(amount)
    else:
        assert nonnegative_amount(amount) == 0


@given(st.integers(min_value=1, max_value=10**9))
def test_a_positive_amount_is_kept_in_minor_units(amount: int) -> None:
    assert positive_amount(amount, 1) == amount * 100
    assert nonnegative_amount(amount) == amount * 100
