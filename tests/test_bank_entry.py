"""Lines typed right in the bank statement (D78), from the keyboard.

Kapital AZN has 10 000.00 from 01.03; the statement of Monday 02.03:
  ALFA, 60.1, 500.00 out              → 9 500.00   (owed nothing: Dt 60.2 [ALFA, Договор 1])
  ALFA again: 60.1 as last time, 200.00 → 9 300.00
  payroll in one sum, 70, 1 000.00 out  → 8 300.00
"""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QSettings, Qt

from modern_gl.application.bank import SALARY, SUPPLIER, bank_places, load_bank_operation
from modern_gl.application.catalog import Catalog
from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.bank_page.entry import ONE, TWO
from modern_gl.desktop.session import Session
from tests.test_bank_ui import acc, setup_company, value
from tests.test_entry_keys import focused, shown_list, type_text
from tests.test_uniform_entry import shown


@pytest.fixture
def bank(conn, ledger) -> Session:
    cid = setup_company(ledger)
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=lambda m: None)
    s.working_date = date(2026, 3, 5)
    return s


def statement_page(qtbot, session) -> BankPage:
    QSettings().setValue("bank/amounts", TWO)
    page = shown(qtbot, BankPage(session))
    azn = next(r for r in page.model.rows if getattr(r, "title", "") == "Kapital AZN")
    page.open_account(azn.place.key)
    page.new_statement()
    assert page.current is not None and page.current.date_from == "2026-03-02"
    return page


def pick(qtbot, box, text: str) -> None:
    """Type into a list field and take the first match with Enter."""
    box.setFocus()
    type_text(box, text)
    qtbot.keyClick(shown_list(qtbot), Qt.Key.Key_Return)


def enter(qtbot) -> None:
    qtbot.keyClick(focused(), Qt.Key.Key_Return)


def enter_until(qtbot, field) -> None:
    """Enter through the fields with nothing to type, up to this one."""
    for _ in range(6):
        if focused() is field:
            return
        enter(qtbot)
    raise AssertionError(f"the cursor stays on {type(focused()).__name__}, not on the field")


def operations(session) -> list:
    rows = session.conn.execute(
        "SELECT id FROM bank_operations WHERE company_id = ? ORDER BY id", (session.company_id,)
    ).fetchall()
    return [load_bank_operation(session.conn, session.company_id, r["id"]) for r in rows]


def test_a_supplier_paid_line_by_line_and_again_as_last_time(qtbot, bank):
    session = bank
    page = statement_page(qtbot, session)
    line = page.entry
    assert focused() is line.counterparty_box  # the statement opens on its entry line
    pick(qtbot, line.counterparty_box, "ALFA")
    assert focused() is line.account  # nothing paid to ALFA before: the account is asked
    pick(qtbot, line.account, "60.1")
    enter_until(qtbot, line.money_out)  # past the e-qaimə field (none unpaid)
    type_text(line.money_out, "500")
    enter(qtbot)
    assert line.error.isHidden(), line.error.text()
    [op] = operations(session)
    assert (op.kind, op.direction, op.status, op.total) == (SUPPLIER, "out", "posted", 50_000)
    # ALFA is owed nothing: paid ahead, an advance on 60.2 (the template's advance account)
    assert op.lines[0].account_id == acc(session, "60.2")
    assert op.lines[0].subconto[:2] == (value(session, "ALFA MMC"), value(session, "Договор 1"))
    assert op.memo == "Оплата поставщику ALFA MMC"
    assert page.current is not None and page.current.closing == 950_000
    assert focused() is line.counterparty_box and line.money_out.text() == ""

    pick(qtbot, line.counterparty_box, "ALFA")
    assert line.account.currentData() == (acc(session, "60.1"), None)  # as last time
    assert focused() is not line.account  # and passed by
    enter_until(qtbot, line.money_out)
    type_text(line.money_out, "200")
    enter(qtbot)
    assert page.current is not None and page.current.closing == 930_000


def test_payroll_in_one_sum_and_a_sign_in_one_column(qtbot, bank):
    session = bank
    page = statement_page(qtbot, session)
    page.set_amount_mode(ONE)
    line = page.entry
    enter(qtbot)  # no counterparty
    assert focused() is line.account
    pick(qtbot, line.account, "70")
    assert focused() is line.analytics  # an employee, if wanted; Enter: none
    enter(qtbot)
    assert focused() is line.amount and line.sign.text() == "расход"
    type_text(line.amount, "1000")
    enter(qtbot)
    [op] = operations(session)
    assert (op.kind, op.total, op.counterparty_id) == (SALARY, 100_000, None)
    assert op.lines[0].subconto[0] is None  # no employee: paid in one sum
    assert page.current is not None and page.current.closing == 900_000
    page.set_amount_mode(TWO)


def test_what_the_line_lacks_is_said_and_the_cursor_stays(qtbot, bank):
    session = bank
    page = statement_page(qtbot, session)
    line = page.entry
    pick(qtbot, line.account, "60.1")
    line.money_out.setFocus()
    type_text(line.money_out, "10")
    enter(qtbot)
    assert operations(session) == []
    assert "контрагент" in line.error.text() and not line.error.isHidden()


def test_a_transfer_to_an_own_account_is_one_line_in_both_statements(qtbot, bank):
    session = bank
    usd = value(session, "Kapital USD")
    page = statement_page(qtbot, session)
    names = [t.split("  ", 1)[-1] for t in items_of(page.entry.account)]
    assert "Kapital USD" not in names  # another currency: only a conversion
    other = session.ledger.bank.add_bank_account(
        session.company_id, "PAŞA AZN", acc(session, "51"), "current"
    )
    page.refresh()
    page.entry.fill_lists()
    line = page.entry
    enter(qtbot)
    pick(qtbot, line.account, "PAŞA")
    enter_until(qtbot, line.money_out)
    type_text(line.money_out, "300")
    enter(qtbot)
    places = {p.value_id: p for p in bank_places(session.conn, session.company_id)}
    from modern_gl.application.bank import place_balance

    assert place_balance(session.conn, session.company_id, places[other], "2026-03-31") == 30_000
    assert usd in places


def items_of(box) -> list[str]:
    return [box.itemText(i) for i in range(box.count())]


def test_lines_move_to_another_account(qtbot, bank, monkeypatch):
    session = bank
    page = statement_page(qtbot, session)
    line = page.entry
    enter(qtbot)
    pick(qtbot, line.account, "70")
    enter_until(qtbot, line.money_out)
    type_text(line.money_out, "100")
    enter(qtbot)
    other = session.ledger.bank.add_bank_account(
        session.company_id, "PAŞA AZN", acc(session, "51"), "current"
    )
    page.refresh()
    page.table.selectRow(0)
    monkeypatch.setattr(
        page, "choose_place", lambda places: next(p for p in places if p.value_id == other)
    )
    page.move_selected()
    [op] = operations(session)
    assert op.subconto[0] == other
    assert page.current is not None and page.current.closing == 1_000_000


def test_marked_lines_are_deleted_with_del(qtbot, bank, monkeypatch):
    """Two payments of 100.00 marked: Del deletes both, the statement is back to the
    opening 10 000.00. In «Все операции» lines are marked too (ƏDV DH over many days)."""
    from PySide6.QtWidgets import QAbstractItemView, QMessageBox

    from modern_gl.desktop.bank_page.actions import JOURNAL, LINES

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    session = bank
    page = statement_page(qtbot, session)
    for _ in range(2):
        page.entry.start()
        enter(qtbot)
        pick(qtbot, page.entry.account, "70")
        enter_until(qtbot, page.entry.money_out)
        type_text(page.entry.money_out, "100")
        enter(qtbot)
    assert len(operations(session)) == 2
    page.table.setFocus()
    page.table.selectAll()
    qtbot.keyClick(page.table, Qt.Key.Key_Delete)
    assert operations(session) == []
    assert page.current is not None and page.current.closing == 1_000_000
    page.view = LINES
    page.go(JOURNAL)
    mode = page.table.selectionMode()
    assert mode == QAbstractItemView.SelectionMode.ExtendedSelection


def owe_alfa(session, number: str, amount: str, day: str) -> None:
    """ALFA's e-qaimə for rent: Dt 26 [rent] / Ct 60.1 [ALFA, Договор 1]."""
    from modern_gl.application.ledger import PostingInput

    led, cid = session.ledger, session.company_id
    rent = led.add_subconto_value(cid, led.subconto_kind_id(cid, "cost_item"), f"Аренда {number}")
    led.post_new(
        cid,
        day,
        [
            PostingInput(
                acc(session, "26"),
                acc(session, "60.1"),
                amount,
                [rent],
                [value(session, "ALFA MMC"), value(session, "Договор 1")],
                invoice=number,
            )
        ],
    )
    session.catalog.reload()


def test_an_overpaid_e_qaime_leaves_an_advance_offset_later(qtbot, bank):
    """MT001 owes 1 180.00; 1 500.00 paid for it: 1 180.00 MT001 on 60.1, 320.00 on 60.2.
    MT002 for 400.00 comes on 03.03: the advance is offset, MT002 still owes 80.00."""
    session = bank
    owe_alfa(session, "MT001", "1180", "2026-03-01")
    page = statement_page(qtbot, session)
    line = page.entry
    pick(qtbot, line.counterparty_box, "ALFA")
    pick(qtbot, line.account, "60.1")
    enter_until(qtbot, line.invoice)
    type_text(line.invoice, "MT001")
    enter(qtbot)
    assert focused() is line.money_out and line.money_out.text() == "1 180.00"
    type_text(line.money_out, "1500")
    enter(qtbot)
    assert line.error.isHidden(), line.error.text()
    [op] = operations(session)
    accounts = session.catalog.accounts
    assert [(accounts[x.account_id].code, x.amount, x.invoice) for x in op.lines] == [
        ("60.1", 118_000, "MT001"),
        ("60.2", 32_000, ""),
    ]

    from modern_gl.application.bank import counterparty_balance
    from modern_gl.application.invoices import open_invoices
    from modern_gl.desktop.bank_page.offset_dialog import AdvanceOffsetDialog

    owe_alfa(session, "MT002", "400", "2026-03-03")
    dialog = AdvanceOffsetDialog(session, "2026-03-03")
    qtbot.addWidget(dialog)
    dialog.counterparty.setCurrentIndex(dialog.counterparty.findData(value(session, "ALFA MMC")))
    dialog.plan()
    assert [o.parts for o in dialog.offsets] == [(("MT002", 32_000),)]
    dialog.offset()
    cid, alfa = session.company_id, value(session, "ALFA MMC")
    assert counterparty_balance(session.conn, cid, acc(session, "60.2"), alfa, "2026-03-31") == 0
    left = {i.invoice: i.amount for i in open_invoices(session.conn, cid, alfa, True, "2026-03-31")}
    assert left == {"MT002": 8_000}


def test_f2_takes_the_line_to_the_full_form(qtbot, bank):
    session = bank
    page = statement_page(qtbot, session)
    line = page.entry
    sent: list = []
    page.new_bank_operation.connect(sent.append)
    pick(qtbot, line.counterparty_box, "ALFA")
    pick(qtbot, line.account, "60.1")
    line.money_out.setFocus()
    type_text(line.money_out, "100")
    qtbot.keyClick(focused(), Qt.Key.Key_F2)
    [data] = sent
    assert (data.counterparty_id, data.direction, data.doc_date) == (
        value(session, "ALFA MMC"),
        "out",
        "2026-03-02",
    )
    assert data.lines[0].account_id == acc(session, "60.2") and data.total == 10_000  # ahead
    assert line.money_out.text() == "" and line.counterparty is None
