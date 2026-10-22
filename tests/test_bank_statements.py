"""Bank statements and bank accounts of the module (D78).

Kapital AZN on 51, hand-calculated:
  01.03  in  10 000.00                  → 10 000.00
  02.03  out  1 200.00, in 300.00       →  9 100.00   bank says 9 100.00: reconciled
  06.03  out     50.00                  →  9 050.00   bank says 9 040.00: −10.00
  07–09.03 (weekend + Monday) out 100.00 on 09.03 → 8 950.00   bank not entered
  10.03  nothing, a statement opened    →  8 950.00
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import (
    CARD,
    CURRENCY,
    CURRENT,
    DIFF,
    OK,
    OPEN,
    bank_accounts,
    bank_places,
    bank_statements,
)
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.chart_csv import apply_chart_template


@pytest.fixture
def firm(ledger):
    cid = ledger.create_company("ООО Выписки")
    apply_chart_template(ledger, cid, "1c77", "ru")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    azn = ledger.add_subconto_value(cid, banks, "Kapital AZN")
    usd = ledger.add_subconto_value(cid, banks, "Kapital USD")
    ledger.set_subconto_value_currency(cid, usd, ledger.currency_id(cid, "USD"))
    owner = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "counterparty"), "Учредитель"
    )
    a51, a80 = ledger.account_id(cid, "51"), ledger.account_id(cid, "80")

    def money(day: str, amount: str, into: bool) -> None:
        line = (
            PostingInput(a51, a80, amount, [azn], [owner])
            if into
            else PostingInput(a80, a51, amount, [owner], [azn])
        )
        ledger.post_new(cid, day, [line])

    money("2026-03-01", "10000", True)
    money("2026-03-02", "1200", False)
    money("2026-03-02", "300", True)
    money("2026-03-06", "50", False)
    money("2026-03-09", "100", False)
    ledger.bank.add_bank_statement(cid, a51, azn, "2026-03-07", "2026-03-09")
    return cid, a51, azn


def place_of(ledger, cid, value_id):
    return next(p for p in bank_places(ledger.conn, cid) if p.value_id == value_id)


def test_days_and_periods_with_their_balances(ledger, firm):
    cid, _, azn = firm
    rows = bank_statements(ledger.conn, cid, place_of(ledger, cid, azn))
    assert [
        (s.date_from, s.date_to, s.opening, s.money_in, s.money_out, s.closing, s.lines)
        for s in rows
    ] == [
        ("2026-03-01", "2026-03-01", 0, 1_000_000, 0, 1_000_000, 1),
        ("2026-03-02", "2026-03-02", 1_000_000, 30_000, 120_000, 910_000, 2),
        ("2026-03-06", "2026-03-06", 910_000, 0, 5_000, 905_000, 1),
        ("2026-03-07", "2026-03-09", 905_000, 0, 10_000, 895_000, 1),
    ]
    assert [s.id is None for s in rows] == [True, True, True, False]  # days not entered yet


def test_the_bank_closing_reconciles_a_statement(ledger, firm):
    cid, a51, azn = firm
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-02", "2026-03-02", 910_000)
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-06", "2026-03-06", 904_000)
    ledger.bank.add_bank_statement(cid, a51, azn, "2026-03-10", "2026-03-10")
    rows = bank_statements(ledger.conn, cid, place_of(ledger, cid, azn))
    assert [(s.date_from, s.status, s.difference) for s in rows] == [
        ("2026-03-01", OPEN, None),
        ("2026-03-02", OK, 0),
        ("2026-03-06", DIFF, -1_000),  # the bank has 10.00 less: a fee not entered?
        ("2026-03-07", OPEN, None),
        ("2026-03-10", OPEN, None),
    ]
    assert (rows[-1].opening, rows[-1].closing, rows[-1].lines) == (895_000, 895_000, 0)
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-06", "2026-03-06", None)
    assert bank_statements(ledger.conn, cid, place_of(ledger, cid, azn))[2].status == OPEN


def test_statements_of_one_account_do_not_overlap(ledger, firm):
    cid, a51, azn = firm
    with pytest.raises(ValidationError, match="уже есть выписка"):
        ledger.bank.add_bank_statement(cid, a51, azn, "2026-03-09", "2026-03-10")
    with pytest.raises(ValidationError, match="раньше"):
        ledger.bank.add_bank_statement(cid, a51, azn, "2026-03-12", "2026-03-11")


def test_bank_accounts_by_group_with_what_is_left_to_check(ledger, firm):
    cid, a51, azn = firm
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-02", "2026-03-02", 910_000)
    ledger.bank.set_bank_closing(cid, a51, azn, "2026-03-06", "2026-03-06", 904_000)
    card = ledger.bank.add_bank_account(
        cid, "ABB Visa", ledger.account_id(cid, "55"), CARD, card_digits="4417"
    )
    rows = bank_accounts(ledger.conn, cid, "2026-03-31")
    assert [
        (r.place.name, r.place.account_code, r.kind, r.balance, r.unchecked, r.differences)
        for r in rows
    ] == [
        ("Kapital AZN", "51", CURRENT, 895_000, 2, 1),
        ("Kapital USD", "52", CURRENCY, 0, 0, 0),
        ("ABB Visa", "55", CARD, 0, 0, 0),
    ]
    assert rows[-1].place.value_id == card and rows[-1].card_digits == "4417"


def test_a_closed_account_and_wrong_card_digits(ledger, firm):
    cid, _, _ = firm
    a55 = ledger.account_id(cid, "55")
    with pytest.raises(ValidationError, match="4 цифры"):
        ledger.bank.add_bank_account(cid, "Yelo Visa", a55, CARD, card_digits="44a7")
    card = ledger.bank.add_bank_account(cid, "Yelo Visa", a55, CARD, card_digits="3388")
    ledger.bank.set_bank_account(cid, a55, card, kind=CARD, card_digits="3388", closed=True)
    row = next(r for r in bank_accounts(ledger.conn, cid, "2026-03-31") if r.place.value_id == card)
    assert row.closed
