"""Finding the way around the bank page (D78): one click goes in, Esc goes back, an
account's statements for a period.

Kapital AZN, hand-calculated:
  20.02  in    500.00   → 500.00
  01.03  in 10 000.00   → 10 500.00
February: on the start 0.00, in 500.00, out 0.00, at the end 500.00.
March: on the start 500.00, in 10 000.00, out 0.00, at the end 10 500.00.
"""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.bank import BankAccount, BankStatement, StatementLine
from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.bank_page.actions import ACCOUNTS, JOURNAL, STATEMENT
from modern_gl.desktop.session import Session
from tests.helpers.bank_ui import setup_company, value
from tests.helpers.entry_keys import focused, type_text
from tests.helpers.uniform_entry import shown


@pytest.fixture
def bank(conn, ledger) -> Session:
    cid = setup_company(ledger)
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=lambda m: None)
    owner = value(s, "Учредитель")
    a51, a80 = ledger.account_id(cid, "51"), ledger.account_id(cid, "80")
    line = PostingInput(a51, a80, "500", [value(s, "Kapital AZN")], [owner])
    ledger.post_new(cid, "2026-02-20", [line])
    s.working_date = date(2026, 3, 5)
    return s


def click_row(qtbot, page: BankPage, row: object) -> None:
    at = page.model.rows.index(row)
    rect = page.table.visualRect(page.model.index(at, 0))
    qtbot.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())


def kapital(page: BankPage) -> BankAccount:
    return next(r for r in page.model.rows if getattr(r, "title", "") == "Kapital AZN")


def test_one_click_opens_an_account_and_a_statement(qtbot, bank):
    page = shown(qtbot, BankPage(bank))
    assert "Щёлкните счёт" in page.footer.text()  # a newcomer is told how to go in
    click_row(qtbot, page, kapital(page))
    assert page.level == JOURNAL
    march = next(r for r in page.model.rows if isinstance(r, BankStatement))
    click_row(qtbot, page, march)
    assert page.level == STATEMENT and page.current == march


def test_esc_goes_back_a_level_unless_the_entry_line_has_text(qtbot, bank):
    page = shown(qtbot, BankPage(bank))
    page.open_account(kapital(page).place.key)
    page.open_statement("2026-03-01", "2026-03-01")
    line = page.entry
    assert focused() is line.counterparty_box  # the statement opens on its entry line
    type_text(line.memo, "оплата")
    qtbot.keyClick(line.memo, Qt.Key.Key_Escape)
    assert page.level == STATEMENT and line.memo.text() == ""  # first the line is emptied
    qtbot.keyClick(focused(), Qt.Key.Key_Escape)
    assert page.level == JOURNAL
    qtbot.keyClick(focused(), Qt.Key.Key_Escape)
    assert page.level == ACCOUNTS
    assert page.up() is False  # the top: Esc goes on to the window


def test_an_accounts_statements_and_lines_for_a_period(qtbot, bank):
    page = shown(qtbot, BankPage(bank))
    page.open_account(kapital(page).place.key)
    assert page.period_dates() == ("2026-03-01", "2026-03-31")  # the working date's month
    assert [(s.date_from, s.closing) for s in page.model.rows] == [("2026-03-01", 1_050_000)]
    assert "На начало 500.00" in page.footer.text()
    assert "на конец 10 500.00" in page.footer.text()

    page.period_field.set_period(date(2026, 2, 1), date(2026, 2, 28))
    assert [(s.date_from, s.closing) for s in page.model.rows] == [("2026-02-20", 50_000)]
    assert "приход 500.00" in page.footer.text()

    page.period_field.set_period(date(2026, 1, 1), date(2026, 3, 31))
    page.view_buttons["lines"].click()  # every line of the period, not by day
    assert all(isinstance(r, StatementLine) for r in page.model.rows)
    assert [(r.doc_date, r.money_in, r.balance) for r in page.model.rows] == [
        ("2026-02-20", 50_000, 50_000),
        ("2026-03-01", 1_000_000, 1_050_000),
    ]
    click_row(qtbot, page, page.model.rows[0])  # a line opens with a double click only
    assert page.level == JOURNAL


def test_back_from_a_statement_past_the_period_shows_its_month(qtbot, bank):
    page = shown(qtbot, BankPage(bank))
    page.open_account(kapital(page).place.key)
    page.period_field.set_period(date(2026, 2, 1), date(2026, 2, 28))
    page.open_statement("2026-03-01", "2026-03-01")
    page.up()
    assert page.period_dates() == ("2026-03-01", "2026-03-31")
    assert page.current is not None and page.current.date_from == "2026-03-01"


def test_the_kind_of_an_account_is_fixed_from_its_row(qtbot, bank, monkeypatch):
    """An AZN account saved as «Валютные счета» by mistake: a right click on its row (or
    «⋯») opens its details, and the kind chosen anew moves it to its group."""
    from modern_gl.desktop.bank_page import actions
    from modern_gl.desktop.bank_page.dialogs import BankAccountDialog

    place = kapital(shown(qtbot, BankPage(bank))).place
    bank.ledger.bank.set_bank_account(
        bank.company_id, place.account_id, place.value_id, kind="currency"
    )
    page = shown(qtbot, BankPage(bank))
    titles = [getattr(r, "title", "") for r in page.model.rows]
    assert titles.index("Валютные счета") < titles.index("Kapital AZN")
    assert "правый щелчок" in page.footer.text()

    def fix(session, account, parent=None) -> bool:  # the window, without its exec()
        dialog = BankAccountDialog(session, account, parent)
        qtbot.addWidget(dialog)
        assert dialog.name.text() == "Kapital AZN" and dialog.kind.currentData() == "currency"
        dialog.kind.setCurrentIndex(dialog.kind.findData("current"))
        dialog.save()
        return True

    monkeypatch.setattr(actions, "edit_bank_account", fix)
    item = page.menu_actions(kapital(page))[0]
    assert item is not None and item[0] == "Реквизиты счёта…" and callable(item[1])
    item[1]()
    assert page.level == ACCOUNTS  # the list stays, the account is in its group
    titles = [getattr(r, "title", "") for r in page.model.rows]
    assert titles[titles.index("Kapital AZN") - 1] == "Расчётные счета"
    # «⋯» of the list offers the same for the account under the cursor
    page.table.setCurrentIndex(page.model.index(page.model.rows.index(kapital(page)), 0))
    assert "Реквизиты счёта…" in [item[0] for item in page.more_items() if item]
    bank.read_only = True  # viewing only (D80): nothing to change
    assert shown(qtbot, BankPage(bank)).menu_actions(kapital(page)) == []
