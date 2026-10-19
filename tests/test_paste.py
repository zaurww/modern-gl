"""Pasting lines from Excel into a document, and copying a document back."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.postings import AMOUNT, CT, DT, MEMO, header_columns, plain_number
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect


@pytest.fixture(autouse=True)
def yes_to_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )


@pytest.fixture
def page(qtbot):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    for kind, name in (
        ("counterparty", "Альфа Трейд"),
        ("contract", "Договор №1"),
        ("cost_item", "Аренда офиса"),
    ):
        ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name)
    s = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda m: None)
    s.working_date = date(2026, 3, 5)
    p = DocumentPage(s)
    qtbot.addWidget(p)
    yield p
    conn.close()


def names(page, row):
    m = page.model
    return [
        m.index(row, c).data() for c in range(m.columnCount()) if not page.table.isColumnHidden(c)
    ]


def test_excel_numbers():
    assert plain_number("1 234,50") == "1234.50"
    assert plain_number("1,234.50") == "1234.50"
    assert plain_number("1.234,50") == "1234.50"
    assert plain_number("1 234") == "1234"
    assert plain_number("400") == "400"


def test_header_line_is_recognised_in_both_languages():
    assert header_columns(["Дебет", "Кредит", "Сумма"]) == [DT, CT, AMOUNT]
    assert header_columns(["Debet", "Subkonto", "Kredit", "Subkonto", "Subkonto", "Məzmun"]) == [
        DT,
        DT + 1,
        CT,
        CT + 1,
        CT + 2,
        MEMO,
    ]
    assert header_columns(["Субконто Кт 2", "Сумма"]) == [CT + 2, AMOUNT]
    assert header_columns(["26", "60", "400"]) is None


def test_lines_without_header_go_in_keyboard_order(page):
    text = (
        "26\tаренда\t60\tальфа\tдоговор №1\t400\tАренда за март\n"
        "50\t51\t\t1 234,50\n"  # 51 needs a bank account: left empty, posting will tell
    )
    page.paste(text)
    m = page.model
    r = m.rows[0]
    cat = page.s.catalog
    assert (r.debit, r.credit, r.amount, r.memo) == (
        cat.by_code["26"].id,
        cat.by_code["60"].id,
        40_000,
        "Аренда за март",
    )
    assert cat.value(r.debit_sc[0]).name == "Аренда офиса"
    assert [cat.value(v).name for v in r.credit_sc[:2]] == ["Альфа Трейд", "Договор №1"]
    assert (m.rows[1].debit, m.rows[1].credit, m.rows[1].amount) == (
        cat.by_code["50"].id,
        cat.by_code["51"].id,
        123_450,
    )
    assert len(m.rows) == 2


def test_header_columns_in_any_order(page):
    page.paste("Сумма\tКредит\tДебет\tСодержание\n100\t50\t71\tПод отчёт\n")
    r = page.model.rows[0]
    cat = page.s.catalog
    assert (r.debit, r.credit, r.amount, r.memo) == (
        cat.by_code["71"].id,
        cat.by_code["50"].id,
        10_000,
        "Под отчёт",
    )


def test_unknown_names_are_added_in_one_go(page):
    page.paste("26\tРеклама\t60\tНовый поставщик\tДоговор №1\t50\n")
    cat = page.s.catalog
    r = page.model.rows[0]
    assert cat.value(r.debit_sc[0]).name == "Реклама"
    assert cat.value(r.credit_sc[0]).name == "Новый поставщик"
    assert page.error.isHidden()


def test_problems_are_listed_and_the_rest_is_pasted(page):
    page.paste("999\t50\t10\n50\t80\tabc\n")
    assert "строка 1" in page.error.text() and "999" in page.error.text()
    assert "строка 2" in page.error.text()
    assert page.model.rows[1].debit == page.s.catalog.by_code["50"].id


def test_copy_and_paste_back(page, qtbot):
    page.paste("26\tаренда\t60\tальфа\tдоговор №1\t400\tАренда\n50\t71\t\t25\n")
    page.copy()
    text = QApplication.clipboard().text()
    assert text.splitlines()[0].startswith("Дебет\tСубконто Дт 1")
    other = DocumentPage(page.s)
    qtbot.addWidget(other)
    other.paste(text)
    assert [names(other, i) for i in range(2)] == [names(page, i) for i in range(2)]


def test_single_cell_goes_into_the_current_cell(page):
    page.paste("26\t\t50\t\t10\n")
    page.table.setCurrentIndex(page.model.index(0, AMOUNT))
    page.paste("15")
    assert len(page.model.rows) == 1
    assert page.model.rows[0].amount == 1_500
