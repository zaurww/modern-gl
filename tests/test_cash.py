"""The cash desk in the bank module (D-new-cash). Hand-calculated, March 2026, the 1C 7.7
chart (50 «Касса», no subconto):

10.03  in, from BETA: Dt 50 / Ct 62.1 [BETA]              300.00
11.03  out, to ALFA:  Dt 60.1 [ALFA] / Ct 50               120.00
12.03  transfer to the bank: Dt 51 [Kapital AZN] / Ct 50   100.00

Cash: 300.00 − 120.00 − 100.00 = 80.00; Kapital AZN: 10 000.00 + 100.00 = 10 100.00.
"""

from __future__ import annotations

import pytest

from modern_gl.application.bank import (
    CUSTOMER,
    FEE,
    IN,
    OUT,
    SUPPLIER,
    TRANSFER,
    BankLine,
    BankOperationInput,
    bank_places,
    place_balance,
    statement,
    transfer_targets,
)
from modern_gl.application.bank.accounts import CASH, bank_accounts
from modern_gl.domain.errors import ValidationError
from tests.helpers.bank import postings


@pytest.fixture
def firm(bank_firm, ledger):
    bank_firm["acc"]["50"] = ledger.account_id(bank_firm["cid"], "50")
    return bank_firm


def cash_op(f, day: str, direction: str, kind: str, line: BankLine, who=None):
    return BankOperationInput(
        doc_date=day,
        direction=direction,
        account_id=f["acc"]["50"],
        kind=kind,
        counterparty_id=who,
        lines=(line,),
    )


def cash_month(ledger, f) -> list[int]:
    acc, v, cid = f["acc"], f["v"], f["cid"]
    ops = [
        cash_op(
            f,
            "2026-03-10",
            IN,
            CUSTOMER,
            BankLine(acc["62.1"], 30000, (None, v["contract_b"])),
            v["beta"],
        ),
        cash_op(
            f,
            "2026-03-11",
            OUT,
            SUPPLIER,
            BankLine(acc["60.1"], 12000, (None, v["contract"])),
            v["alfa"],
        ),
        cash_op(f, "2026-03-12", OUT, TRANSFER, BankLine(acc["51"], 10000, (v["azn"],))),
    ]
    return [ledger.bank.save_bank_operation(cid, op, post=True) for op in ops]


def cash_place(ledger, f):
    return next(p for p in bank_places(ledger.conn, f["cid"]) if p.is_cash)


def test_an_unused_cash_desk_is_not_listed(ledger, firm):
    assert not any(p.is_cash for p in bank_places(ledger.conn, firm["cid"]))


def test_cash_comes_and_goes_with_its_postings(ledger, firm):
    acc, v = firm["acc"], firm["v"]
    came, paid, moved = cash_month(ledger, firm)
    assert [
        (p.debit_account_id, p.credit_account_id, p.amount) for p in postings(ledger, firm, came)
    ] == [(acc["50"], acc["62.1"], 30000)]
    assert [
        (p.debit_account_id, p.credit_account_id, p.amount) for p in postings(ledger, firm, paid)
    ] == [(acc["60.1"], acc["50"], 12000)]
    to_bank = postings(ledger, firm, moved)
    assert [(p.debit_account_id, p.credit_account_id, p.amount) for p in to_bank] == [
        (acc["51"], acc["50"], 10000)
    ]
    assert to_bank[0].debit_subconto[0] == v["azn"]
    cash = cash_place(ledger, firm)
    assert (cash.account_code, cash.name) == ("50", "Касса")
    assert place_balance(ledger.conn, firm["cid"], cash, "2026-03-31") == 8000
    bank = next(p for p in bank_places(ledger.conn, firm["cid"]) if p.value_id == v["azn"])
    assert place_balance(ledger.conn, firm["cid"], bank, "2026-03-31") == 1010000


def test_a_day_of_the_cash_book(ledger, firm):
    cash_month(ledger, firm)
    st = statement(ledger.conn, firm["cid"], cash_place(ledger, firm), "2026-03-11", "2026-03-11")
    assert (st.opening, st.total_in, st.total_out, st.closing) == (30000, 0, 12000, 18000)


def test_the_cash_desk_is_its_own_group_with_nothing_to_check(ledger, firm):
    cash_month(ledger, firm)
    listed = bank_accounts(ledger.conn, firm["cid"], "2026-03-31")
    cash = listed[0]
    assert (cash.kind, cash.balance, cash.unchecked, cash.differences) == (CASH, 8000, 0, 0)
    assert all(a.kind != CASH for a in listed[1:])


def test_cash_goes_to_a_bank_account_of_its_currency(ledger, firm):
    cash_month(ledger, firm)
    cash = cash_place(ledger, firm)
    names = [p.name for p in transfer_targets(ledger.conn, firm["cid"], cash.key, None)]
    assert names == ["Kapital AZN", "PAŞA AZN"]


def test_a_cash_desk_has_no_bank_fee(ledger, firm):
    op = cash_op(firm, "2026-03-10", OUT, FEE, BankLine(firm["acc"]["91.2"], 200))
    with pytest.raises(ValidationError, match="комиссии банка"):
        ledger.bank.save_bank_operation(firm["cid"], op, post=True)


# ---- the papers: cash orders and the cash book --------------------------------------


def test_a_cash_order_of_money_taken_in(ledger, firm):
    from modern_gl.application.bank.cash_book import cash_order

    came, paid, _ = cash_month(ledger, firm)
    cash = cash_place(ledger, firm)
    order = cash_order(ledger.conn, firm["cid"], cash, came_doc(ledger, firm, came))
    assert (order.incoming, order.doc_date, order.corr, order.party, order.amount) == (
        True,
        "2026-03-10",
        "62.1",
        "BETA MMC",
        30000,
    )
    out = cash_order(ledger.conn, firm["cid"], cash, came_doc(ledger, firm, paid))
    assert (out.incoming, out.corr, out.amount) == (False, "60.1", 12000)


def came_doc(ledger, firm, operation_id) -> int:
    from modern_gl.application.bank import load_bank_operation

    return load_bank_operation(ledger.conn, firm["cid"], operation_id).document_id


def test_the_cash_book_is_a_sheet_per_day(ledger, firm):
    from modern_gl.application.bank.cash_book import cash_book

    cash_month(ledger, firm)
    book = cash_book(ledger.conn, firm["cid"], cash_place(ledger, firm), "2026-03-11", "2026-03-31")
    # 10.03 is before the period: the first sheet opens with its 300.00
    assert [(d.day, d.opening, d.money_in, d.money_out, d.closing) for d in book.days] == [
        ("2026-03-11", 30000, 0, 12000, 18000),
        ("2026-03-12", 18000, 0, 10000, 8000),
    ]
    assert book.desk.account == "50"


def test_the_papers_in_excel(ledger, firm, tmp_path):
    import openpyxl

    from modern_gl.application.bank.cash_book import cash_book, cash_order
    from modern_gl.i18n import set_language
    from modern_gl.infrastructure.cash_file import write_cash_book_xlsx, write_cash_order_xlsx

    came, _, _ = cash_month(ledger, firm)
    cash = cash_place(ledger, firm)
    set_language("az")
    try:
        path = tmp_path / "order.xlsx"
        write_cash_order_xlsx(
            cash_order(ledger.conn, firm["cid"], cash, came_doc(ledger, firm, came)), path
        )
        texts = [c for row in openpyxl.load_workbook(path).worksheets[0].values for c in row]
        assert any(isinstance(t, str) and t.startswith("KASSA MƏDAXİL ORDERİ") for t in texts)
        assert "Üç yüz manat 00 qəpik" in texts  # in the order and in its receipt
        assert texts.count("Üç yüz manat 00 qəpik") == 2
        path = tmp_path / "book.xlsx"
        write_cash_book_xlsx(
            cash_book(ledger.conn, firm["cid"], cash, "2026-03-01", "2026-03-31"), path
        )
        sheet = openpyxl.load_workbook(path).worksheets[0]
        rows = [list(r) for r in sheet.values]
        totals = [r for r in rows if r[1] == "Gün ərzində cəmi"]
        closing = [r for r in rows if r[1] == "Günün sonuna qalıq"]
        assert len(totals) == len(closing) == 3  # 10, 11 and 12 March
        assert all(str(r[3]).startswith("=SUM(") for r in totals)
        assert all(str(r[3]).startswith("=D") for r in closing)
        assert len(sheet.row_breaks.brk) == 2
    finally:
        set_language("ru")
