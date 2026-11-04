"""«Заполнить остатком…»: the balance of an account by subconto becomes a document's lines.

The golden example (conftest), by hand:
  531 [A]: Ct 1 200.00 (01-10), Dt 1 000.00 (01-15)        → credit 200.00
  531 [B]: Ct 500.00 (02-03)                                → credit 500.00
  22: 221 = 10 000.00 − 1 000.00 − 2 000.00 = 7 000.00 Dt; 222 = 2 000.00 Dt
Currencies (helpers/currency.post_example), 31.03.2026:
  52 [bank]: 1 700.00 − 513.00 = 1 187.00 Dt, USD 1 000 − 300 = 700
  60 [supplier]: −850.00 + 513.00 = 337.00 Ct, USD −500 + 300 = −200
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from modern_gl.application.balance_fill import BalanceLine, balance_lines
from modern_gl.application.books import TAX
from modern_gl.application.catalog import Catalog
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.document_page.fill import balance_row
from modern_gl.desktop.fill_balance_dialog import FillBalanceDialog
from modern_gl.desktop.session import Session
from tests.helpers.currency import post_example
from tests.helpers.qt import running_app


def test_a_credit_balance_by_counterparty(demo):
    lines = balance_lines(demo.ledger.conn, demo.company_id, demo.acc["531"], "2026-02-28")
    assert lines == [
        BalanceLine(demo.acc["531"], (demo.supplier_a, None, None), -20000),
        BalanceLine(demo.acc["531"], (demo.supplier_b, None, None), -50000),
    ]


def test_on_an_earlier_day_and_without_the_document_being_filled(demo):
    conn, cid, acc = demo.ledger.conn, demo.company_id, demo.acc["531"]
    january = balance_lines(conn, cid, acc, "2026-01-31")
    assert [ln.amount for ln in january] == [-20000]
    without_b = balance_lines(conn, cid, acc, "2026-02-28", without_document=demo.docs[3])
    assert [ln.subconto[0] for ln in without_b] == [demo.supplier_a]


def test_a_group_gives_each_of_its_accounts(demo):
    lines = balance_lines(demo.ledger.conn, demo.company_id, demo.acc["22"], "2026-02-28")
    assert [(ln.account_id, ln.amount) for ln in lines] == [
        (demo.acc["221"], 700000),
        (demo.acc["222"], 200000),
    ]


def test_nothing_left_no_line_and_drafts_do_not_count(demo):
    led, cid = demo.ledger, demo.company_id
    led.post_new(cid, "2026-02-25", [demo.p("531", "221", "500", dt_sc=[demo.supplier_b])])
    led.create_draft(cid, "2026-02-26", [demo.p("531", "221", "200", dt_sc=[demo.supplier_a])])
    lines = balance_lines(led.conn, cid, demo.acc["531"], "2026-02-28")
    assert [(ln.subconto[0], ln.amount) for ln in lines] == [(demo.supplier_a, -20000)]


def test_the_tax_book_adds_its_adjustments(demo):
    led, cid = demo.ledger, demo.company_id
    led.post_new(cid, "2026-02-27", [demo.p("721", "201", "50")], layer="tax_adj")
    common = balance_lines(led.conn, cid, demo.acc["201"], "2026-02-28")
    tax = balance_lines(led.conn, cid, demo.acc["201"], "2026-02-28", TAX)
    assert [ln.amount for ln in common] == [140000]  # 1 200 + 500 − 300
    assert [ln.amount for ln in tax] == [135000]  # and − 50 in the tax book


def test_currency_balances_keep_their_currency(ledger, currency_books):
    post_example(ledger, currency_books)
    cid, acc, usd, bank, supplier = currency_books
    assert balance_lines(ledger.conn, cid, acc["52"], "2026-03-31") == [
        BalanceLine(acc["52"], (bank, None, None), 118700, usd, 70000)
    ]
    assert balance_lines(ledger.conn, cid, acc["60"], "2026-03-31") == [
        BalanceLine(acc["60"], (supplier, None, None), -33700, usd, -20000)
    ]


def test_the_line_brings_the_balance_to_zero():
    debit = balance_row(BalanceLine(12, (7, None, None), 29000), other_id=26)
    assert (debit.debit, debit.credit, debit.credit_sc, debit.amount) == (
        26,
        12,
        [7, None, None],
        29000,
    )
    credit = balance_row(BalanceLine(60, (3, None, None), -33700, 1, -20000), other_id=None)
    assert (credit.debit, credit.debit_sc, credit.credit, credit.amount) == (
        60,
        [3, None, None],
        None,
        33700,
    )
    assert (credit.currency_id, credit.currency_amount) == (1, 20000)
    assert credit.rate == Fraction(33700, 20000) and not credit.rate_auto


@pytest.fixture
def session(qtbot, demo):
    theme.apply(running_app())
    conn, cid = demo.ledger.conn, demo.company_id
    messages: list[str] = []
    return Session(conn, demo.ledger, cid, "ООО Тест", Catalog(conn, cid), notify=messages.append)


def test_the_document_writes_off_the_balance_and_posts(session, demo, qtbot, monkeypatch):
    """12-style: Dt 721 Ct 531 per supplier, posted on 28.02 — 531 is left with nothing."""
    page = DocumentPage(session)
    qtbot.addWidget(page)
    page.date.setDate(page.date.date().fromString("2026-02-28", "yyyy-MM-dd"))
    assert "Заполнить остатком…" in [i[0] for i in page.menu_items() if i]

    def answer(dialog: FillBalanceDialog) -> int:
        dialog.choose(demo.acc["531"], demo.acc["721"])
        assert dialog.found.text() == "Строк: 2 · кредит 700.00"
        dialog.accept()
        return 1

    monkeypatch.setattr(FillBalanceDialog, "exec", answer)
    page.fill_from_balance()
    rows = page.model.rows
    assert [(r.debit, r.debit_sc[0], r.credit, r.amount) for r in rows] == [
        (demo.acc["531"], demo.supplier_a, demo.acc["721"], 20000),
        (demo.acc["531"], demo.supplier_b, demo.acc["721"], 50000),
    ]
    assert page.save(post=True), page.error.text()
    assert balance_lines(demo.ledger.conn, demo.company_id, demo.acc["531"], "2026-02-28") == []
    # filled again in the posted document: its own lines are not part of the balance
    monkeypatch.setattr(FillBalanceDialog, "exec", answer)
    page.fill_from_balance()
    assert len(page.model.rows) == 4


def test_no_balance_nothing_to_fill(session, demo, qtbot):
    dialog = FillBalanceDialog(session, "2026-01-01", ("common",), None)
    qtbot.addWidget(dialog)
    dialog.choose(demo.acc["531"])
    assert dialog.found.text() == "На эту дату у счёта нет остатка"
    assert not dialog.ok.isEnabled()
