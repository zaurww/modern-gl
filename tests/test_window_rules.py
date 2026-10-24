"""Accounting rules that lived in windows, now in application (debt 9, session 38): the
figures counted by hand."""

from __future__ import annotations

from fractions import Fraction

import pytest

from modern_gl.application.bank import (
    BankLine,
    BankOperationInput,
    split_by_deposit,
    vat_deposit_part,
)
from modern_gl.application.conversion import ConversionInput, ConversionSide, official_rate
from modern_gl.application.currencies import Rate
from modern_gl.application.inventory import default_vat_rate, line_vat
from modern_gl.application.ledger import Ledger, PostingInput, opening_posting
from modern_gl.demo_data import create_demo_company
from modern_gl.infrastructure.db import connect


def test_line_vat_follows_the_amount_at_the_rate():
    assert line_vat("receipt", 120000, 1800) == 21600  # 1 200.00 × 18 % = 216.00
    assert line_vat("sale", 5, 1800) == 1  # 0.05 × 18 % = 0.009 → 0.01
    assert line_vat("sale", 120000, 0) == 0
    assert line_vat("transfer", 120000, 1800) is None  # no VAT on a transfer
    assert line_vat("receipt", None, 1800) is None
    assert line_vat("receipt", 120000, None) is None


def test_a_new_receipt_has_the_standard_vat_when_there_is_a_vat_account():
    led = Ledger(connect(":memory:"))
    create_demo_company(led)
    cid = led.conn.execute("SELECT id FROM companies").fetchone()["id"]
    assert default_vat_rate(led, cid, "receipt") == 1800  # 19 is the input VAT account
    assert default_vat_rate(led, cid, "issue") is None


def test_a_credit_balance_is_00_on_the_debit():
    typed = PostingInput(5, 9, "100", (1, None, None), (), "", invoice="MT1")
    assert opening_posting(typed, on_credit=False) is typed  # Дт 60 / Кт 00
    flipped = opening_posting(typed, on_credit=True)  # Дт 00 / Кт 60 [1]
    assert (flipped.debit_account_id, flipped.credit_account_id) == (9, 5)
    assert (tuple(flipped.debit_subconto), tuple(flipped.credit_subconto)) == ((), (1, None, None))
    assert (flipped.amount, flipped.invoice) == ("100", "MT1")


def test_vat_deposit_split_and_its_operation():
    # e-qaimə 1 180.00 with ƏDV 180.00: 1 000.00 from the bank, 180.00 from the deposit
    assert split_by_deposit(118000, 18000, with_deposit=True, on_deposit=False) == (100000, 18000)
    # paid from the deposit account itself: only the ƏDV; without ƏDV — all of it
    assert split_by_deposit(118000, 18000, with_deposit=False, on_deposit=True) == (18000, 0)
    assert split_by_deposit(50000, 0, with_deposit=False, on_deposit=True) == (50000, 0)
    payment = BankOperationInput(
        "2026-03-02",
        "out",
        51,
        (BankLine(60, 100000, (7,), "MT1"),),
        subconto=(3,),
        currency_id=None,
        counterparty_id=7,
        reference="REF1",
    )
    part = vat_deposit_part(payment, 54, (4, None, None), 18000, "2026-03-05")
    assert part is not None
    assert (part.doc_date, part.account_id, part.subconto, part.reference) == (
        "2026-03-05",
        54,
        (4, None, None),
        "",
    )
    assert part.lines == (BankLine(60, 18000, (7,), "MT1"),)
    assert part.counterparty_id == 7
    assert vat_deposit_part(payment, 54, (4,), 0, "2026-03-05") is None


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (None, 1, Fraction(17, 10)),  # manat → USD: 1.70 manat per dollar
        (1, None, Fraction(17, 10)),  # USD → manat
        (1, 2, Fraction(170, 185)),  # USD → EUR: 1.70 / 1.85 = 0.9189… euro per dollar
        (2, 3, None),  # no rate of the third currency
    ],
)
def test_official_rate_and_the_cross(source, target, expected):
    rates = {
        1: Rate(1, "2026-03-02", 1_700_000, 1, "cbar"),
        2: Rate(2, "2026-03-02", 1_850_000, 1, "cbar"),
    }
    data = ConversionInput(
        "2026-03-02",
        ConversionSide(51, 100, currency_id=source),
        ConversionSide(52, 100, currency_id=target),
    )
    assert official_rate(data, rates) == expected
