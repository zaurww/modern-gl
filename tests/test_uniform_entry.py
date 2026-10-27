"""The same keyboard entry in every form as in the journal (D54): Enter goes on as Tab
does, a name the list lacks is added from the list ("+ Добавить «…»") without a window,
and a refused name keeps the cursor in its cell."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.conversion_page import ConversionPage
from modern_gl.desktop.inventory_document_page import WAREHOUSE, InventoryDocumentPage
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.templates_page import TemplatePage
from tests.helpers.bank_ui import setup_company
from tests.helpers.entry_keys import editor, focused, items, shown_list, type_text
from tests.helpers.sales import make_shop
from tests.helpers.uniform_entry import shown


@pytest.fixture(autouse=True)
def no_windows(monkeypatch):
    """No window may open: a test that needs one says so. Questions are answered "no"."""
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )

    def no_dialog(*_):
        raise AssertionError("a window opened")

    monkeypatch.setattr(QDialog, "exec", no_dialog)


@pytest.fixture
def bank_session(conn, ledger):
    cid = setup_company(ledger)
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=lambda m: None)
    s.working_date = date(2026, 3, 5)
    return s


def test_bank_counterparty_is_added_from_the_list(qtbot, bank_session):
    page = shown(qtbot, BankOperationPage(bank_session))
    box = page.counterparty_edit
    box.setFocus()
    type_text(box, "Yeni MMC")
    popup = shown_list(qtbot)
    assert items(popup) == ["+ Добавить «Yeni MMC»"]
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert box.text() == "Yeni MMC"
    assert bank_session.catalog.value(page.counterparty).name == "Yeni MMC"
    assert focused() is not box  # and on to the next field


def test_bank_known_counterparty_is_not_offered_to_add(qtbot, bank_session):
    page = shown(qtbot, BankOperationPage(bank_session))
    page.counterparty_edit.setFocus()
    type_text(page.counterparty_edit, "alfa mmc")
    assert items(shown_list(qtbot)) == ["ALFA MMC  ·  1234567890"]


def test_conversion_is_typed_with_enter_field_after_field(qtbot, bank_session):
    page = shown(qtbot, ConversionPage(bank_session))
    assert isinstance(page.source.account, PickBox)
    page.memo.setFocus()
    qtbot.keyClick(page.memo, Qt.Key.Key_Return)
    assert focused() is page.source.account
    qtbot.keyClick(page.source.account, Qt.Key.Key_Return)
    assert focused() is next(b for b in page.source.sc if b.isVisible())


def test_conversion_fee_rows_follow_in_the_enter_order(qtbot, bank_session):
    page = shown(qtbot, ConversionPage(bank_session))
    page.target.reference.setFocus()
    qtbot.keyClick(page.target.reference, Qt.Key.Key_Insert)  # Ins: a new fee, cursor in it
    row = page.fee_rows[0]
    qtbot.waitUntil(row.amount.isVisible)  # a row added to a shown page shows a moment later
    assert focused() is row.amount
    page.target.reference.setFocus()
    qtbot.keyClick(page.target.reference, Qt.Key.Key_Return)
    assert focused() is row.amount


@pytest.fixture
def receipt(conn, qtbot):
    shop = make_shop(conn, "classic")
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    session.working_date = date(2026, 3, 5)
    return shown(qtbot, InventoryDocumentPage(session, doc_type="receipt"))


def test_stock_document_header_goes_on_with_enter(qtbot, receipt):
    page = receipt
    page.memo.setFocus()
    qtbot.keyClick(page.memo, Qt.Key.Key_Return)
    assert focused() is page.date
    qtbot.keyClick(page.date, Qt.Key.Key_Return)
    assert focused() is page.vat_rate


def edit_warehouse(page) -> QLineEdit:
    index = page.model.index(0, page.model.columns.index(WAREHOUSE))
    page.table.setFocus()
    page.table.setCurrentIndex(index)
    page.table.edit(index)
    return editor()


def test_a_new_warehouse_is_added_from_the_list(qtbot, receipt):
    page = receipt
    type_text(edit_warehouse(page), "Yeni anbar")
    popup = shown_list(qtbot)
    assert items(popup)[-1] == "+ Добавить «Yeni anbar»"
    popup.setCurrentIndex(popup.model().index(popup.model().rowCount() - 1, 0))
    qtbot.keyClick(popup, Qt.Key.Key_Return)  # no question: it was picked to be added
    column = page.model.columns.index(WAREHOUSE)
    qtbot.waitUntil(lambda: page.model.data(page.model.index(0, column)) == "Yeni anbar")


def test_a_refused_warehouse_keeps_the_cursor_in_its_cell(qtbot, receipt):
    page = receipt
    editor = edit_warehouse(page)
    editor.setText("Yeni anbar")  # typed with the list closed: a question, answered "no"
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    column = page.model.columns.index(WAREHOUSE)
    qtbot.waitUntil(
        lambda: any(
            e.isVisible() and e.text() == "Yeni anbar" for e in page.table.findChildren(QLineEdit)
        )
    )
    assert page.table.currentIndex().column() == column


def test_template_name_and_memo_go_on_into_the_lines(qtbot, bank_session):
    page = shown(qtbot, TemplatePage(bank_session))
    page.name.setFocus()
    qtbot.keyClick(page.name, Qt.Key.Key_Return)
    assert focused() is page.memo
    qtbot.keyClick(page.memo, Qt.Key.Key_Return)
    assert page.table.state() == page.table.State.EditingState


@pytest.mark.parametrize("how", ["click", "tab", "code"])
def test_a_chosen_value_is_selected_whole_on_entering_its_field(qtbot, how):
    """Typing into a field that shows a choice replaces it (D78): "70" typed over
    "60 Malsatan…" is not "7060 Malsatan…", however the cursor came in."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    window = QWidget()
    lay = QVBoxLayout(window)
    before = QLineEdit()
    box = PickBox()
    for code, name in (("60", "Malsatanlar"), ("70", "Əmək haqqı")):
        box.addItem(f"{code}  {name}", code)
    box.setCurrentIndex(0)
    lay.addWidget(before)
    lay.addWidget(box)
    shown(qtbot, window)
    before.setFocus()
    if how == "click":
        QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(4, box.height() // 2))
    elif how == "tab":
        QTest.keyClick(before, Qt.Key.Key_Tab)
    else:
        box.setFocus()
    qtbot.waitUntil(lambda: box.selectedText() == "60  Malsatanlar")
