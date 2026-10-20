"""In the interface: contracts of the line's counterparty, 60 in manat or "500 USD",
Central Bank rates right from the document, suggestions in the quick entry line."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QPersistentModelIndex
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.desktop import theme
from modern_gl.desktop.directories_page import DirectoriesPage, ValueDialog
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.postings import AMOUNT, CT, CURRENCY, CURRENCY_AMOUNT, DT
from modern_gl.desktop.quick_entry_bar import QuickEntryBar
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import parse_rate
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )


@pytest.fixture
def session(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    cp = ledger.subconto_kind_id(cid, "counterparty")
    ct = ledger.subconto_kind_id(cid, "contract")
    alfa = ledger.add_subconto_value(cid, cp, "Альфа")
    beta = ledger.add_subconto_value(cid, cp, "Бета")
    ledger.add_subconto_value(cid, ct, "Фактура 15", owner_id=alfa)
    ledger.add_subconto_value(cid, ct, "Договор Бета", owner_id=beta)
    ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    messages: list[str] = []
    s = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=messages.append)
    s.working_date = date(2026, 3, 5)
    s.fetch_rates = lambda day: {"USD": (parse_rate("1.75"), 1)}  # no network in tests
    yield s
    conn.close()


def value(s: Session, name: str) -> int:
    return next(
        v.id for kind in s.catalog.kinds for v in s.catalog.all_values(kind) if v.name == name
    )


def rent_line(page: DocumentPage) -> None:
    m, cat = page.model, page.s.catalog
    m.setData(m.index(0, DT), cat.by_code["26"].id)
    m.setData(m.index(0, DT + 1), value(page.s, "Аренда"))
    m.setData(m.index(0, CT), cat.by_code["60"].id)


def test_manat_line_on_60_shows_no_currency_columns(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    rent_line(page)
    m = page.model
    assert m.applies(0, CURRENCY) and not m.applies(0, CURRENCY_AMOUNT)
    assert page.table.isColumnHidden(CURRENCY)
    m.setData(m.index(0, CT + 1), value(session, "Альфа"))
    m.setData(m.index(0, CT + 2), value(session, "Фактура 15"))
    m.setData(m.index(0, AMOUNT), m.parse(0, AMOUNT, "400"))
    assert page.save(post=True), page.error.text()


def test_amount_with_a_currency_makes_the_line_a_dollar_one(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    rent_line(page)
    m = page.model
    m.setData(m.index(0, AMOUNT), m.parse(0, AMOUNT, "500 usd"))
    r = m.rows[0]
    assert (r.currency_amount, r.amount) == (50_000, 85_000)  # 500 × 1.70 = 850.00
    assert m.index(0, CURRENCY).data() == "USD"
    assert not page.table.isColumnHidden(CURRENCY_AMOUNT)
    m.setData(m.index(0, CURRENCY), None)  # back to manat: the amount stays
    assert (r.currency_id, r.currency_amount, r.amount) == (None, None, 85_000)


def test_contract_list_is_the_counterparty_s(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    rent_line(page)
    m = page.model
    m.setData(m.index(0, CT + 1), value(session, "Бета"))
    items = page.delegate._subconto_items(m, 0, CT + 2)
    assert items == ["Договор Бета"]
    assert m.parse(0, CT + 2, "договор") == value(session, "Договор Бета")
    m.setData(m.index(0, CT + 2), value(session, "Договор Бета"))
    m.setData(m.index(0, CT + 1), value(session, "Альфа"))  # another partner
    assert m.rows[0].credit_sc[1] is None  # Бета's contract left the line


def test_new_contract_from_the_line_belongs_to_its_counterparty(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    rent_line(page)
    m = page.model
    m.setData(m.index(0, CT + 1), value(session, "Бета"))
    contracts = session.catalog.by_code["60"].sc_kinds[1]
    page._create_value(QPersistentModelIndex(m.index(0, CT + 2)), contracts, "Фактура 15")
    new = session.catalog.value(m.rows[0].credit_sc[1])
    assert (new.name, new.owner_id) == ("Фактура 15", value(session, "Бета"))


def test_rate_of_the_document_date_is_loaded_from_the_document(session, qtbot):
    page = DocumentPage(session)
    qtbot.addWidget(page)
    page.date.setDate(page.date.date().addDays(20))  # 25.03: only the rate of 01.03
    rent_line(page)
    m = page.model
    m.setData(m.index(0, AMOUNT), m.parse(0, AMOUNT, "100 USD"))
    assert m.rows[0].amount == 17_000
    assert not page.rate_note.isHidden()
    assert "от 01.03.2026" in page.rate_text.text()
    page.load_rates()
    assert m.rows[0].amount == 17_500  # 100 × 1.75
    assert page.rate_note.isHidden()


def test_quick_entry_offers_what_comes_next(session, qtbot):
    bar = QuickEntryBar(session)
    qtbot.addWidget(bar)
    bar.edit.setText("26 ")
    assert bar.suggest() == ["Аренда"]
    bar.take("Аренда")
    assert bar.edit.text() == "26 Аренда / "
    bar.edit.setText("26 Аренда / 60 Бета, ")
    assert bar.suggest() == ["Договор Бета"]
    bar.take("Договор Бета")
    assert bar.edit.text() == "26 Аренда / 60 Бета, Договор Бета "


def test_directory_shows_whose_contract_and_adds_one(session, qtbot, monkeypatch):
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    contracts = session.catalog.by_code["60"].sc_kinds[1]
    page.refresh(select_kind=contracts)
    texts = {page.model.index(r, 0).data(): page.model.index(r, 1).data() for r in range(2)}
    assert texts == {"Фактура 15": "Альфа", "Договор Бета": "Бета"}

    def accept(dialog: ValueDialog) -> int:
        dialog.name.setText("Договор 2")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", accept)
    page.add_value(contracts, value(session, "Альфа"))  # "Добавить в «Договоры»…"
    new = next(v for v in session.catalog.all_values(contracts) if v.name == "Договор 2")
    assert new.owner_id == value(session, "Альфа")
