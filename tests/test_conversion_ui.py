"""The currency conversion page: sides, the calculation under them, posting, the journal."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.conversion import load_conversion
from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.conversion_page import ConversionPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import parse_rate
from modern_gl.infrastructure.db import connect

pytestmark = pytest.mark.questions("Yes")  # deleting, posting: yes


def setup_company(ledger: Ledger) -> int:
    cid = ledger.create_company("ООО Валюта")
    apply_chart_template(ledger, cid, "1c77", "ru")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    usd = ledger.currency_id(cid, "USD")
    bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    ledger.set_subconto_value_currency(cid, bank, usd)
    ledger.add_subconto_value(cid, banks, "Kapital Bank AZN")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    return cid


@pytest.fixture
def session(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = setup_company(ledger)
    messages: list[str] = []
    s = Session(conn, ledger, cid, "ООО Валюта", Catalog(conn, cid), notify=messages.append)
    s.working_date = date(2026, 3, 5)
    yield s
    conn.close()


def choose(box, text: str) -> None:
    i = box.findText(text)
    assert i >= 0, text
    box.setCurrentIndex(i)
    box.activated.emit(i)


def type_text(edit, text: str) -> None:
    edit.setText(text)
    edit.textEdited.emit(text)


def fill_sale(page: ConversionPage) -> None:
    """1 000 USD sold for 1 695.00 AZN; fee 2.00 USD (rate 1.70: 3.40 AZN)."""
    choose(page.source.sc[0], "Kapital Bank USD")
    type_text(page.source.amount, "1000")
    choose(page.target.sc[0], "Kapital Bank AZN")
    type_text(page.target.amount, "1695")
    type_text(page.add_fee().amount, "2")  # taken from the account sold from


def test_new_conversion_shows_rates_and_difference(qtbot, session):
    page = ConversionPage(session)
    qtbot.addWidget(page)
    # a currency account on the left, a manat one on the right
    assert page.source.account_info.code == "52"
    assert page.target.account_info.code == "51"
    fill_sale(page)
    assert page.source.code() == "USD" and not page.source.currency.isEnabled()
    assert page.cbar.value.text() == "1 USD = 1.7000 AZN"
    assert page.bank.value.text() == "1 USD = 1.6950 AZN"
    assert page.difference.value.text() == "5.00 убыток"
    assert page.fee_value.value.text() == "3.40"
    # the rate is of 01.03, not of the date itself: the official one can be loaded
    assert page.rate_note.isVisibleTo(page)
    session.fetch_rates = lambda day: {"USD": (1_701_000, 1)}
    page.load_rates()
    assert not page.rate_note.isVisibleTo(page)
    assert page.difference.value.text() == "6.00 убыток"

    assert page.save(post=True)
    assert page.doc is not None and page.doc.status == "posted"
    assert page.title() == f"Конвертация №{page.doc.number}"
    assert page.btn_unpost.isVisibleTo(page) and not page.btn_save.isVisibleTo(page)


def test_errors_stay_on_the_page(qtbot, session):
    page = ConversionPage(session)
    qtbot.addWidget(page)
    choose(page.source.sc[0], "Kapital Bank USD")
    type_text(page.source.amount, "1000")
    assert not page.save(post=True)
    assert "зачислено" in page.error.text()
    assert page.save(post=False)  # a draft without the second side
    assert page.doc is not None and page.doc.status == "draft"


def test_journal_opens_the_conversion_and_its_postings_are_read_only(qtbot, tmp_path):
    theme.apply(QApplication.instance())
    workspace = Workspace(tmp_path / "data")
    conn = connect(workspace.new_path("ООО Валюта"))
    setup_company(Ledger(conn))
    conn.close()
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.open_session.working_date = date(2026, 3, 5)
    win.show_place(("journal",))
    try:
        win.show_place(("bank",))  # conversions start in the bank module
        win.pages[("bank",)].new_conversion.emit()
        page = win.stack.currentWidget()
        assert isinstance(page, ConversionPage)
        fill_sale(page)
        assert page.save(post=True)
        doc = page.doc
        assert doc is not None and ("conversion", doc.id) in win.pages

        journal = win.pages[("journal",)]
        assert doc.document_id in {d.id for d in journal.model.docs}
        win.close_page(("conversion", doc.id))
        win.open_document(doc.document_id)
        assert isinstance(win.stack.currentWidget(), ConversionPage)

        win.stack.currentWidget().btn_gl.click()
        gl = win.stack.currentWidget()
        assert isinstance(gl, DocumentPage) and gl.model.read_only

        win.copy_document(doc.document_id)  # F9: a new conversion like this one
        copy = win.stack.currentWidget()
        assert isinstance(copy, ConversionPage) and copy.doc is None
        assert copy.source.reference.text() == ""
        assert copy.target.amount.text() == "1 695.00"
        assert load_conversion(win.open_session.conn, win.open_session.company_id, doc.id)
    finally:
        win.shutdown()


def test_the_credit_day_opens_the_same_conversion(qtbot, tmp_path):
    """A conversion credited on a later day has two GL documents; the window learns from
    document_owners that either opens (and F9 copies) the conversion (debt 12)."""
    theme.apply(QApplication.instance())
    workspace = Workspace(tmp_path / "data")
    conn = connect(workspace.new_path("ООО Валюта"))
    setup_company(Ledger(conn))
    conn.close()
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.open_session.working_date = date(2026, 3, 5)
    try:
        win.show_place(("bank",))
        win.pages[("bank",)].new_conversion.emit()
        page = win.stack.currentWidget()
        assert isinstance(page, ConversionPage)
        fill_sale(page)
        page.target.date.setDate(QDate(2026, 3, 6))
        assert page.save(post=True)
        doc = page.doc
        assert doc is not None and doc.credit_document_id is not None
        win.close_page(("conversion", doc.id))

        win.open_document(doc.credit_document_id)
        opened = win.stack.currentWidget()
        assert isinstance(opened, ConversionPage) and opened.doc is not None
        assert opened.doc.id == doc.id

        win.copy_document(doc.credit_document_id)
        copy = win.stack.currentWidget()
        assert isinstance(copy, ConversionPage) and copy.doc is None
        assert copy.target.amount.text() == "1 695.00"
    finally:
        win.shutdown()


def test_missing_account_is_asked_for_and_the_conversion_posts(qtbot, session, monkeypatch):
    from modern_gl.desktop.conversion_page import ConversionAccountsDialog
    from modern_gl.domain.accounts import FX_TRANSIT

    transit = session.ledger.account_role(session.company_id, FX_TRANSIT)
    session.ledger.set_account_role(session.company_id, FX_TRANSIT, None)
    session.ledger.set_account_type(session.company_id, transit, "other_asset")
    asked: list[bool] = []

    def choose_transit(dialog: ConversionAccountsDialog) -> int:
        asked.append(True)
        box = dialog.boxes[FX_TRANSIT]
        box.setCurrentIndex(box.findData(transit))
        dialog.accept()
        return 1

    monkeypatch.setattr(ConversionAccountsDialog, "exec", choose_transit)
    page = ConversionPage(session)
    qtbot.addWidget(page)
    fill_sale(page)
    assert page.save(post=True)
    assert page.doc is not None and page.doc.status == "posted"
    assert len(asked) == 1


def test_several_fees_from_different_accounts(qtbot, session):
    """2.00 USD from the USD account (3.40) and 1.50 AZN from the manat one: 4.90 AZN."""
    page = ConversionPage(session)
    qtbot.addWidget(page)
    fill_sale(page)
    second = page.add_fee()
    choose(second.place, "Kapital Bank AZN  ·  51")
    assert second.currency.currentText() == "AZN" and not second.currency.isEnabled()
    type_text(second.amount, "1.50")
    assert page.fee_value.value.text() == "4.90"
    assert page.save(post=True)
    assert page.doc is not None and len(page.doc.fees) == 2
    assert [f.amount for f in page.doc.fees] == [200, 150]

    # a fee removed leaves the other one
    page.fee_rows[0].remove.click()
    assert page.fee_value.value.text() == "1.50"
    assert page.save(post=True)
    assert page.doc is not None and [f.amount for f in page.doc.fees] == [150]
