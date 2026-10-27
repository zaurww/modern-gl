"""Amounts the e-taxes portal sends (e-qaimə, ƏDV DH) become minor units by one rule
(«Долг» 14, the user's choice): halves away from zero, as the program rounds ƏDV."""

from __future__ import annotations

from decimal import Decimal

import pytest

from modern_gl.domain.eqaime import portal_invoice
from modern_gl.domain.money import portal_minor


@pytest.mark.parametrize(
    ("sent", "minor"),
    [
        (Decimal("12.4369"), 1244),
        ("0.125", 13),  # a half goes up (banker's rounding gave 0.12)
        ("0.135", 14),
        (Decimal("-0.125"), -13),  # away from zero
        (150, 15000),
        (None, 0),
        ("", 0),
    ],
)
def test_a_portal_amount(sent, minor):
    assert portal_minor(sent) == minor


def test_not_a_number_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="не число"):
        portal_minor("12,4a")


def test_the_e_qaime_list_and_details_round_alike():
    row = {"serialNumber": "MT2610000001", "vat": "0.125", "costWithoutVat": "1.005"}
    invoice = portal_invoice(row, False)
    assert invoice is not None and (invoice.vat, invoice.amount) == (13, 101)
