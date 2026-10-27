"""Keyboard entry in the document form: Enter and Tab go the same way, field after field;
the grid reached from the keyboard has its cell open for typing; a name a directory
lacks is added from the list ("+ Добавить «…»") without a dialog."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.new_cell_value import add_typed_value
from modern_gl.desktop.postings import AMOUNT, CT, DT, PostingsTable
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.db import connect
from tests.helpers.entry_keys import focused, items, shown_list, type_text


@pytest.fixture(autouse=True)
def answer_no(monkeypatch):
    """A modal dialog would block a headless test forever: answer 'no'."""
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )


@pytest.fixture
def books():
    """Parallel books on: the header has the «Book» field (D63)."""
    return True


@pytest.fixture
def page(qtbot, books):
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    ledger.set_parallel_books(cid, books)
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda m: None)
    session.working_date = date(2026, 3, 5)
    page = DocumentPage(session)
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    yield page
    conn.close()


def editing_at(page: DocumentPage, col: int) -> bool:
    table = page.table
    return (
        table.state() == PostingsTable.State.EditingState
        and table.currentIndex().column() == col
        and focused().parent() is table.viewport()
    )


def account(page: DocumentPage, code: str) -> int:
    return page.s.catalog.by_code[code].id


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Tab])
def test_header_goes_field_by_field_into_an_open_cell(page, qtbot, key):
    page.memo.setFocus()
    qtbot.keyClick(page.memo, key)
    assert focused() is page.date
    qtbot.keyClick(page.date, key)  # one key for the whole date, not day → month → year
    assert focused() is page.layer
    qtbot.keyClick(page.layer, key)
    assert editing_at(page, DT)  # the cursor is in the first cell: typing goes there


@pytest.mark.parametrize("books", [False])
def test_one_book_has_no_book_field(page, qtbot, books):
    assert not page.layer.isVisible()
    page.date.setFocus()
    qtbot.keyClick(page.date, Qt.Key.Key_Return)
    assert editing_at(page, DT)  # straight from the date into the first cell


def test_shift_tab_goes_back_through_the_header(page, qtbot):
    page.layer.setFocus()
    qtbot.keyClick(page.layer, Qt.Key.Key_Backtab)
    assert focused() is page.date
    qtbot.keyClick(page.date, Qt.Key.Key_Backtab)
    assert focused() is page.memo


def test_tab_in_the_grid_goes_as_enter_does(page, qtbot):
    table, m = page.table, page.model
    table.setFocus(Qt.FocusReason.TabFocusReason)
    type_text(focused(), "20")  # 20 has one subconto: cost item
    qtbot.keyClick(focused(), Qt.Key.Key_Tab)
    assert m.rows[0].debit == account(page, "20")
    assert editing_at(page, DT + 1)
    qtbot.keyClick(focused(), Qt.Key.Key_Tab)  # left empty; subconto 2 of 20 is skipped
    assert editing_at(page, CT)
    type_text(focused(), "50")
    qtbot.keyClick(focused(), Qt.Key.Key_Tab)  # 50 has no subconto
    assert editing_at(page, AMOUNT)
    qtbot.keyClick(focused(), Qt.Key.Key_Backtab)
    assert editing_at(page, CT)


def test_tab_on_a_cell_not_being_edited_opens_the_next_one(page, qtbot):
    table, m = page.table, page.model
    table.setFocus()
    table.setCurrentIndex(m.index(0, DT))
    qtbot.keyClick(table, Qt.Key.Key_Tab)
    assert editing_at(page, CT)  # 1st row's Dt has no account yet: no subconto cells


def test_a_new_name_is_added_from_the_list_without_a_dialog(page, qtbot):
    table, m = page.table, page.model
    m.setData(m.index(0, DT), account(page, "20"))
    table.setCurrentIndex(m.index(0, DT + 1))
    table.edit(m.index(0, DT + 1))
    type_text(focused(), "Elave")
    popup = shown_list(qtbot)
    assert items(popup) == ["+ Добавить «Elave»"]
    assert popup.currentIndex().row() == 0  # Enter takes it
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    added = m.rows[0].debit_sc[0]
    assert added is not None and page.s.catalog.value(added).name == "Elave"
    assert editing_at(page, CT)  # and on to the next cell


def test_a_known_name_is_not_offered_to_add(page, qtbot):
    m = page.model
    m.setData(m.index(0, DT), account(page, "20"))
    kind = page.s.catalog.accounts[account(page, "20")].sc_kinds[0]
    add_typed_value(page.s, kind, "Аренда")
    page.table.setCurrentIndex(m.index(0, DT + 1))
    page.table.edit(m.index(0, DT + 1))
    type_text(focused(), "аренда")
    assert items(shown_list(qtbot)) == ["Аренда"]


def test_a_refused_name_keeps_the_cursor_in_its_cell(page, qtbot):
    """Enter on a name with the list closed asks; "no" leaves the name to correct."""
    table, m = page.table, page.model
    m.setData(m.index(0, DT), account(page, "20"))
    table.setCurrentIndex(m.index(0, DT + 1))
    table.edit(m.index(0, DT + 1))
    focused().setText("Elave")  # typed with the list closed
    qtbot.keyClick(focused(), Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: table.state() == PostingsTable.State.EditingState)
    assert table.currentIndex().column() == DT + 1
    editors = [e for e in table.viewport().findChildren(QLineEdit) if e.isVisible()]
    assert [e.text() for e in editors] == ["Elave"]
    assert m.rows[0].debit_sc[0] is None
