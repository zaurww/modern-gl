"""The bank module (D46): the statement page and the form of an operation."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QListView, QMessageBox

from modern_gl.application.bank import (
    IN,
    OUT,
    SUPPLIER,
    TAX,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import load_document
from modern_gl.desktop import theme
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.conversion_page import ConversionPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import parse_rate
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))


def setup_company(ledger: Ledger) -> int:
    """Kapital AZN with 10 000.00 from 01.03, Kapital USD; ALFA (VÖEN 1234567890) with
    its contract."""
    cid = ledger.create_company("ООО Банк")
    apply_chart_template(ledger, cid, "1c77", "ru")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    partners = ledger.subconto_kind_id(cid, "counterparty")
    contracts = ledger.subconto_kind_id(cid, "contract")
    azn = ledger.add_subconto_value(cid, banks, "Kapital AZN")
    usd_bank = ledger.add_subconto_value(cid, banks, "Kapital USD")
    ledger.set_subconto_value_currency(cid, usd_bank, ledger.currency_id(cid, "USD"))
    alfa = ledger.add_subconto_value(cid, partners, "ALFA MMC")
    ledger.set_subconto_value_tax(cid, alfa, "1234567890")
    ledger.add_subconto_value(cid, contracts, "Договор 1", owner_id=alfa)
    owner = ledger.add_subconto_value(cid, partners, "Учредитель")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.post_new(
        cid,
        "2026-03-01",
        [
            PostingInput(
                ledger.account_id(cid, "51"), ledger.account_id(cid, "80"), "10000", [azn], [owner]
            )
        ],
    )
    return cid


@pytest.fixture
def session(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = setup_company(ledger)
    messages: list[str] = []
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=messages.append)
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


def acc(session: Session, code: str) -> int:
    return session.catalog.by_code[code].id


def value(session: Session, name: str) -> int:
    return next(
        v.id for k in session.catalog.kinds for v in session.catalog.all_values(k) if v.name == name
    )


def new_page(qtbot, session: Session, prefill=None) -> BankOperationPage:
    page = BankOperationPage(session, prefill=prefill)
    qtbot.addWidget(page)
    return page


def pay_alfa(page: BankOperationPage) -> None:
    """1 180.00 to ALFA found by its VÖEN, e-qaimə MT001."""
    choose(page.sc[0], "Kapital AZN")
    type_text(page.counterparty_edit, "1234567890")
    page.counterparty_edit.editingFinished.emit()
    line = page.line_rows[0]
    type_text(line.amount, "1180")
    type_text(line.invoice, "MT001")


def test_payment_to_a_supplier_found_by_voen(qtbot, session):
    page = new_page(qtbot, session)
    # a new one: money out of the first bank account, to a supplier
    assert page.btn_out.isChecked() and page.kind.currentData() == SUPPLIER
    assert page.bank_info is not None and page.bank_info.code == "51"
    assert page.title() == "Новый расход"
    pay_alfa(page)
    assert page.counterparty_edit.text() == "ALFA MMC"
    assert page.tax_id.text() == "VÖEN 1234567890"
    line = page.line_rows[0]
    # nothing paid to ALFA before: the supplier's account; its only contract is taken
    assert line.account_info is not None and line.account_info.code == "60.1"
    assert line.sc[0].isHidden()  # the counterparty is the operation's
    assert line.sc[1].currentText() == "Договор 1"
    assert page.total.text() == "1 180.00 AZN"
    assert page.memo.placeholderText() == "Оплата поставщику ALFA MMC"

    assert page.save(post=True)
    assert page.doc is not None and page.doc.status == "posted"
    assert page.title() == f"Расход №{page.doc.number}"
    [p] = load_document(session.conn, session.company_id, page.doc.document_id).postings
    assert (p.debit_account_id, p.credit_account_id, p.amount, p.invoice) == (
        acc(session, "60.1"),
        acc(session, "51"),
        118000,
        "MT001",
    )
    assert p.debit_subconto == (value(session, "ALFA MMC"), value(session, "Договор 1"), None)
    assert p.memo == "Оплата поставщику ALFA MMC"
    assert page.btn_unpost.isVisibleTo(page) and not page.btn_save.isVisibleTo(page)


def test_lines_as_last_time_for_the_counterparty(qtbot, session):
    """ALFA was paid an advance from 60.2 last time: the next payment suggests 60.2."""
    cid = session.company_id
    alfa, contract = value(session, "ALFA MMC"), value(session, "Договор 1")
    session.ledger.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-03-02",
            direction=OUT,
            account_id=acc(session, "51"),
            subconto=(value(session, "Kapital AZN"),),
            kind=SUPPLIER,
            counterparty_id=alfa,
            lines=(BankLine(acc(session, "60.2"), 5000, (None, contract)),),
            memo="Аванс",
        ),
        post=True,
    )
    page = new_page(qtbot, session)
    pay_alfa(page)
    line = page.line_rows[0]
    assert line.account_info is not None and line.account_info.code == "60.2"
    assert line.sc[1].currentData() == contract
    assert line.amount.text() == "1180"


def test_tax_has_no_counterparty(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.kind, "Налоги")
    assert page.counterparty_edit.isHidden()
    assert page.line_rows[0].account_info is not None
    assert page.line_rows[0].account_info.code == "68.1"
    assert page.memo.placeholderText() == "Уплата налогов"
    choose(page.sc[0], "Kapital AZN")
    type_text(page.line_rows[0].amount, "180")
    assert page.save(post=True)
    assert page.doc is not None and page.doc.kind == TAX and page.doc.counterparty_id is None


def test_bank_fee_line_and_a_receipt(qtbot, session):
    """Money in from ALFA (a refund): 100.00, and the bank takes 1.50 of it — in two
    lines: Dt 51 / Ct 60.1 100.00, and the fee line goes the same way."""
    page = new_page(qtbot, session)
    page.btn_in.click()
    assert page.title().startswith("Новый приход")
    pay_alfa(page)
    page.add_fee()
    fee = page.line_rows[1]
    assert fee.account_info is not None and fee.account_info.code == "91.2"
    assert fee.sc[0].currentText() == "Комиссия банка"
    type_text(fee.amount, "1.50")
    assert page.total.text() == "1 181.50 AZN"
    page.line_rows[1].remove.click()
    assert page.total.text() == "1 180.00 AZN"


def test_operation_in_dollars_offers_the_rate(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.account, "52  Валютные счета")
    assert page.currency.currentText() == "USD" and not page.currency.isEnabled()
    # the rate is of 01.03, not of the date itself: the official one can be loaded
    assert page.rate_note.isVisibleTo(page)
    session.fetch_rates = lambda day: {"USD": (1_701_000, 1)}
    page.load_rates()
    assert not page.rate_note.isVisibleTo(page)


def test_vat_deposit_offers_only_what_it_may_pay(qtbot, session):
    session.ledger.set_account_type(session.company_id, acc(session, "55"), "vat_deposit")
    session.catalog.reload()
    page = new_page(qtbot, session)
    choose(page.account, "55  Специальные счета в банках")
    view = page.kind.view()
    assert isinstance(view, QListView)
    hidden = {page.kind.itemText(i) for i in range(page.kind.count()) if view.isRowHidden(i)}
    assert hidden == {"Зарплата", "Комиссия банка", "Прочее"}


def test_errors_stay_on_the_page_and_a_draft_is_saved(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    assert not page.save(post=True)
    assert page.error.text() == "строка 1: нулевая сумма"  # the supplier's line
    type_text(page.line_rows[0].amount, "abc")
    assert not page.save(post=True)
    assert page.error.isVisibleTo(page)
    type_text(page.line_rows[0].amount, "10")
    assert page.save(post=False)
    assert page.doc is not None and page.doc.status == "draft"


def test_bank_page_statement(qtbot, session):
    page = BankPage(session)
    qtbot.addWidget(page)
    places = [page.places.item(i).text() for i in range(page.places.count())]
    assert places == ["Kapital AZN", "Kapital USD"]
    assert page.place is not None and page.place.name == "Kapital AZN"
    assert page.model.rowCount() == 1  # the opening entry of 01.03
    assert "остаток на конец 10 000.00 AZN" in page.footer.text()
    emitted: list[BankOperationInput] = []
    page.new_bank_operation.connect(emitted.append)
    page.new_operation(IN)
    [prefill] = emitted
    assert (prefill.direction, prefill.account_id, prefill.doc_date) == (
        IN,
        acc(session, "51"),
        "2026-03-05",
    )
    assert prefill.subconto[0] == value(session, "Kapital AZN")
    # the form takes what is known: the account and its bank account
    form = new_page(qtbot, session, prefill)
    assert form.btn_in.isChecked() and form.sc[0].currentText() == "Kapital AZN"
    assert not form.is_dirty()


def test_the_journal_opens_the_operation(qtbot, tmp_path):
    theme.apply(QApplication.instance())
    workspace = Workspace(tmp_path / "data")
    conn = connect(workspace.new_path("ООО Банк"))
    setup_company(Ledger(conn))
    conn.close()
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.open_session.working_date = date(2026, 3, 5)
    try:
        win.show_place(("bank",))
        bank = win.pages[("bank",)]
        assert isinstance(bank, BankPage)
        bank.new_operation(OUT)
        page = win.stack.currentWidget()
        assert isinstance(page, BankOperationPage)
        pay_alfa(page)
        assert page.save(post=True)
        doc = page.doc
        assert doc is not None and ("bank_op", doc.id) in win.pages
        assert bank.model.rowCount() == 2  # the statement follows

        win.close_page(("bank_op", doc.id))
        win.open_document(doc.document_id)  # from the journal or a report
        assert isinstance(win.stack.currentWidget(), BankOperationPage)
        win.stack.currentWidget().btn_gl.click()
        gl = win.stack.currentWidget()
        assert isinstance(gl, DocumentPage) and gl.model.read_only

        win.copy_document(doc.document_id)  # F9: a new operation like this one
        copy = win.stack.currentWidget()
        assert isinstance(copy, BankOperationPage) and copy.doc is None
        assert copy.line_rows[0].amount.text() == "1 180.00"
        assert copy.line_rows[0].invoice.text() == ""
        session = win.open_session
        assert load_bank_operation(session.conn, session.company_id, doc.id).total == 118000

        bank.new_conversion.emit()  # the conversion moved here from the journal
        assert isinstance(win.stack.currentWidget(), ConversionPage)
    finally:
        win.shutdown()
