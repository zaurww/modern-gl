"""A resident's VÖEN is read in one place (review, session 47): the company's own, a
counterparty's and the portal's dialog."""

from __future__ import annotations

import pytest

from modern_gl.domain.errors import ValidationError
from modern_gl.domain.tax_id import resident_tax_id


def test_a_voen_is_ten_digits_without_spaces():
    assert resident_tax_id(" 1234 567 890 ") == "1234567890"
    assert resident_tax_id("") is None
    assert resident_tax_id(None) is None


@pytest.mark.parametrize("typed", ["123456789", "12345678901", "12345A7890"])
def test_anything_else_is_named(typed):
    with pytest.raises(ValidationError, match=rf"^VÖEN — 10 цифр, а не «{typed}»$"):
        resident_tax_id(typed)


def test_the_company_and_a_counterparty_read_it_alike(ledger):
    cid = ledger.create_company("ООО VÖEN")
    kind = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    value = ledger.add_subconto_value(cid, kind, "ALFA MMC")
    ledger.set_company_tax_id(cid, "1234 567 890")
    ledger.set_subconto_value_tax(cid, value, "1234 567 891")
    for action in (
        lambda: ledger.set_company_tax_id(cid, "12345"),
        lambda: ledger.set_subconto_value_tax(cid, value, "12345"),
    ):
        with pytest.raises(ValidationError, match=r"^VÖEN — 10 цифр, а не «12345»$"):
            action()
