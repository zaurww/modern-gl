"""A posting typed in a form or the quick line (amounts in minor units) becomes the
ledger's input in one place — `typed_posting` (debt 12)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from modern_gl.application.ledger.inputs import PostingInput, typed_posting
from modern_gl.application.quick_entry.parser import QuickLine
from modern_gl.desktop.postings.columns import PostingRow
from modern_gl.domain.errors import ValidationError


def test_a_typed_line_in_minor_units_becomes_the_ledgers_input():
    """123.45 AZN = 100.00 USD on 52 [7] / 60.1 [3, 4], memo trimmed, e-qaimə kept."""
    line = PostingRow(
        debit=11,
        debit_sc=[7, None, None],
        credit=22,
        credit_sc=[3, 4, None],
        amount=12_345,
        memo="  Оплата ",
        currency_id=2,
        currency_amount=10_000,
        invoice="MT1",
    )
    assert typed_posting(1, line) == PostingInput(
        11,
        22,
        Decimal("123.45"),
        (7, None, None),
        (3, 4, None),
        "Оплата",
        2,
        Decimal("100.00"),
        "MT1",
    )
    # an account without currency or e-qaimə: they are not passed on
    plain = typed_posting(1, line, currency=False, invoice=False)
    assert (plain.currency_id, plain.currency_amount, plain.invoice) == (None, None, "")


def test_the_form_and_the_quick_line_give_the_same_input():
    fields: dict[str, Any] = dict(debit=11, credit=22, amount=500, memo="Аренда", invoice="MT2")
    assert typed_posting(1, PostingRow(**fields)) == typed_posting(1, QuickLine(**fields))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"debit": None}, "строка 3: не указан счёт дебета"),
        ({"credit": None}, "строка 3: не указан счёт кредита"),
        ({"amount": None}, "строка 3: не указана сумма"),
    ],
)
def test_what_is_missing_is_named_with_its_line(changes, message):
    line = PostingRow(**{"debit": 11, "credit": 22, "amount": 500, **changes})
    with pytest.raises(ValidationError, match=f"^{message}$"):
        typed_posting(3, line)
