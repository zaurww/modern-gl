"""Currency in the UI: posting lines in currency, rates on the document date,
the Currencies page (CBAR rates, revaluation), reports with amounts in currency."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.desktop import theme
from modern_gl.desktop.currencies_page import CurrenciesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.postings import AMOUNT, CT, CURRENCY, CURRENCY_AMOUNT, MEMO, RATE
from modern_gl.desktop.reports_page import CardPage, OsvPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import CURRENCY_OPTIONAL, parse_rate
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))


@pytest.fixture
def session(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("ООО Валюта")
    apply_chart_template(ledger, cid, "classic", "ru")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    usd = ledger.currency_id(cid, "USD")
    bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    ledger.set_subconto_value_currency(cid, bank, usd)
    ledger.add_subconto_value(cid, banks, "AZN счёт")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.set_rate(cid, "USD", "2026-03-20", parse_rate("1.71"))
    messages: list[str] = []
    s = Session(conn, ledger, cid, "ООО Валюта", Catalog(conn, cid), notify=messages.append)
    s.working_date = date(2026, 3, 5)
    s.messages = messages  # type: ignore[attr-defined]
    yield s
    conn.close()


def ids(s: Session):
    cat = s.catalog
    bank = next(v.id for v in cat.all_values(cat.by_code["52"].sc_kinds[0]) if v.currency_id)
    return cat.by_code["52"].id, cat.by_code["50"].id, bank


def test_currency_line_follows_the_rate_of_the_document_date(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    m = page.model
    acc52, acc50, bank = ids(session)
    m.setData(m.index(0, 0), acc52)
    assert m.applies(0, CURRENCY)
    m.setData(m.index(0, 1), bank)  # a USD bank account brings its currency
    assert m.index(0, CURRENCY).data() == "USD"
    assert m.index(0, RATE).data() == "1.7000"
    m.setData(m.index(0, CT), acc50)
    m.setData(m.index(0, CURRENCY_AMOUNT), 100_000)  # 1 000.00 USD
    assert m.rows[0].amount == 170_000

    page.date.setDate(page.date.date().addDays(20))  # 25.03: the rate of 20.03
    assert m.index(0, RATE).data() == "1.7100"
    assert m.rows[0].amount == 171_000

    assert page.save(post=True), page.error.text()
    [p] = page.doc.postings
    usd = session.ledger.currency_id(session.company_id, "USD")
    assert (p.amount, p.currency_amount, p.currency_id) == (171_000, 100_000, usd)


def test_typed_rate_and_amount_stay(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    m = page.model
    acc52, acc50, bank = ids(session)
    for col, value in ((0, acc52), (1, bank), (CT, acc50), (CURRENCY_AMOUNT, 10_000)):
        m.setData(m.index(0, col), value)
    m.setData(m.index(0, RATE), Fraction(7, 4))  # 1.75 typed over the offered rate
    assert m.rows[0].amount == 17_500
    page.date.setDate(page.date.date().addDays(20))
    assert m.rows[0].amount == 17_500  # a typed rate does not follow the date
    m.setData(m.index(0, AMOUNT), 17_490)
    assert m.rows[0].amount == 17_490


def test_line_without_currency_accounts_skips_currency_cells(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    page.show()
    m, table = page.model, page.table
    cat = session.catalog
    assert table.isColumnHidden(CURRENCY)  # no line in currency yet
    m.setData(m.index(0, 0), cat.by_code["50"].id)
    m.setData(m.index(0, CT), cat.by_code["71"].id)
    assert not m.applies(0, CURRENCY) and not m.applies(0, RATE)
    m.setData(m.index(0, AMOUNT), 1000)
    [p] = m.to_inputs()
    assert p.currency_id is None and p.currency_amount is None
    # account changed from 52 to 50: the line loses its currency
    _, _, bank = ids(session)
    m.setData(m.index(0, 0), cat.by_code["52"].id)
    m.setData(m.index(0, 1), bank)
    assert m.rows[0].currency_id is not None
    assert not table.isColumnHidden(CURRENCY)
    m.setData(m.index(0, 0), cat.by_code["50"].id)
    assert m.rows[0].currency_id is None
    assert table.isColumnHidden(CURRENCY)
    assert MEMO == AMOUNT + 1


def test_posting_without_currency_on_a_currency_account_is_explained(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    m = page.model
    cat = session.catalog
    banks = cat.by_code["52"].sc_kinds[0]
    plain = next(v.id for v in cat.all_values(banks) if v.currency_id is None)
    m.setData(m.index(0, 0), cat.by_code["52"].id)
    m.setData(m.index(0, 1), plain)
    m.setData(m.index(0, CT), cat.by_code["51"].id)
    m.setData(m.index(0, AMOUNT), 1000)
    assert not page.save(post=True)
    assert "не указана валюта" in page.error.text()


def test_currencies_page_loads_cbar_rates_and_revalues(session, qtbot):
    page = CurrenciesPage(session)
    qtbot.addWidget(page)
    page.fetch = lambda day: {"USD": (parse_rate("1.72"), 1), "JPY": (1_130_000, 100)}
    assert page.load_rates(date(2026, 3, 30), date(2026, 3, 31)) == 2
    usd = session.ledger.currency_id(session.company_id, "USD")
    assert session.catalog.currencies[usd].code == "USD"
    assert page.currency().code == "EUR"  # first in the list
    page.refresh(select=usd)
    assert page.model.rows[0].rate_date == "2026-03-31"
    assert page.model.index(0, 3).data() == "ЦБА (cbar.az)"

    acc52, acc50, bank = ids(session)
    session.ledger.post_new(
        session.company_id,
        "2026-03-05",
        [PostingInput(acc52, acc50, "170.00", (bank,), (), "", usd, "100.00")],
    )
    opened = []
    page.open_document.connect(opened.append)
    acc80 = session.catalog.by_code["80"].id
    doc = page.run_revaluation(date(2026, 3, 31), acc80, acc80)
    assert opened == [doc]  # 100 USD × 1.72 = 172.00: +2.00
    assert page.run_revaluation(date(2026, 3, 31), acc80, acc80) is None
    assert "не нужна" in session.messages[-1]


def test_no_connection_is_reported_once(session, qtbot):
    from modern_gl.infrastructure.cbar import RatesUnavailable

    page = CurrenciesPage(session)
    qtbot.addWidget(page)
    calls = []

    def offline(day):
        calls.append(day)
        raise RatesUnavailable("Не удалось связаться с сайтом ЦБА (cbar.az): offline")

    page.fetch = offline
    assert page.load_rates(date(2026, 3, 1), date(2026, 3, 10)) == 0
    assert len(calls) == 1


def test_osv_and_card_show_amounts_in_currency(session, qtbot):
    acc52, acc50, bank = ids(session)
    usd = session.ledger.currency_id(session.company_id, "USD")
    session.ledger.post_new(
        session.company_id,
        "2026-03-05",
        [PostingInput(acc52, acc50, "170.00", (bank,), (), "", usd, "100.00")],
    )
    params = ReportParams(date(2026, 3, 1), date(2026, 3, 31))
    osv = OsvPage(session, params)
    qtbot.addWidget(osv)
    osv.in_currency.setChecked(True)
    names = [osv.model.index(i, 1).data() for i in range(osv.model.rowCount())]
    row = names.index("      USD  ·  в валюте")
    assert osv.model.index(row, 6).data() == "100.00"  # closing Dt in USD
    assert osv.model.index(osv.model.rowCount() - 1, 6).data() == "170.00"  # total in AZN

    card = CardPage(session, acc52, params)
    qtbot.addWidget(card)
    headers = [card.model.columns[i].title for i in range(7)]
    assert headers[4:7] == ["Валюта", "Дт в валюте", "Кт в валюте"]
    assert card.model.index(0, 5).data() == "100.00"
    assert "USD 100.00 Дт" in card.footer.text()


def test_account_dialog_sets_currency_accounting(session, qtbot):
    from modern_gl.desktop.account_dialog import AccountDialog

    dialog = AccountDialog(session, None)
    qtbot.addWidget(dialog)
    dialog.code.setText("55")
    dialog.name.setText("Аккредитивы")
    dialog.currency.setCurrentIndex(dialog.currency.findData(CURRENCY_OPTIONAL))
    dialog.save()
    session.catalog.reload()
    assert session.catalog.by_code["55"].currency_optional


def type_into_cell(qtbot, page: DocumentPage, row: int, col: int, text: str) -> None:
    idx = page.model.index(row, col)
    page.table.setCurrentIndex(idx)
    page.table.edit(idx)
    editor = QApplication.focusWidget()
    editor.setText(text)
    qtbot.keyClick(editor, Qt.Key.Key_Return)


def test_keyboard_entry_goes_through_currency_cells(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    m, table = page.model, page.table
    acc52, _, bank = ids(session)
    m.setData(m.index(0, 0), acc52)
    m.setData(m.index(0, 1), bank)
    type_into_cell(qtbot, page, 0, CT, "50")
    assert table.currentIndex().column() == CURRENCY  # Kt 50 has no subconto
    type_into_cell(qtbot, page, 0, CURRENCY, "usd")
    assert table.currentIndex().column() == CURRENCY_AMOUNT
    type_into_cell(qtbot, page, 0, CURRENCY_AMOUNT, "1 000")
    assert table.currentIndex().column() == RATE
    assert m.rows[0].amount == 170_000
    type_into_cell(qtbot, page, 0, RATE, "1,75")
    assert table.currentIndex().column() == AMOUNT
    assert m.rows[0].amount == 175_000
