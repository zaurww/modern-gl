"""«Только склад» (D90): a company kept as a warehouse only — the books are made unseen."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import company_mode
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.inventory_document_page.columns import ACCOUNT, ITEM, SC1
from modern_gl.desktop.inventory_document_page.lines_base import InventoryGridRow
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.landed_cost_page.columns import ACCOUNT as CHARGE_ACCOUNT
from modern_gl.desktop.landed_cost_page.columns import SC1 as CHARGE_SC1
from modern_gl.desktop.main_window import MainWindow
from modern_gl.domain.company import FULL, STOCK_ONLY
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    )


@pytest.fixture
def workspace(tmp_path):
    ws = Workspace(tmp_path / "data")
    conn = connect(ws.new_path("Anbar MMC"))
    ledger = Ledger(conn)
    company_id = create_demo_company(ledger)
    ledger.set_company_mode(company_id, STOCK_ONLY)
    conn.close()
    return ws


@pytest.fixture
def window(qtbot, workspace):
    theme.apply(QApplication.instance())
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 3, 5)
    win.show()
    yield win
    win.shutdown()


def places(win) -> list:
    nav = win.sidebar.nav
    keys = [nav.item(i).data(Qt.ItemDataRole.UserRole) for i in range(nav.count())]
    return [key for key in keys if key is not None]


def test_company_mode_is_set_checked_and_audited(ledger, conn):
    company_id = ledger.create_company("Firma")
    assert company_mode(conn, company_id) == FULL
    ledger.set_company_mode(company_id, STOCK_ONLY)
    assert company_mode(conn, company_id) == STOCK_ONLY
    with pytest.raises(ValidationError, match="Неизвестный режим"):
        ledger.set_company_mode(company_id, "bank")
    actions = conn.execute(
        "SELECT action FROM audit_events WHERE entity = 'company' AND entity_id = ?",
        (company_id,),
    ).fetchall()
    assert [row[0] for row in actions][-1] == "set_mode"


def test_new_company_file_may_be_a_warehouse_only(tmp_path):
    ws = Workspace(tmp_path / "data")
    path = ws.create("Anbar", mode=STOCK_ONLY)
    conn, company_id = ws.open(path)
    assert company_mode(conn, company_id) == STOCK_ONLY
    assert conn.execute(  # the chart is there all the same: the postings need it
        "SELECT COUNT(*) FROM accounts WHERE company_id = ?", (company_id,)
    ).fetchone()[0]
    conn.close()


def test_sidebar_shows_only_the_warehouse_and_its_lists(window):
    assert places(window) == [
        ("inventory",),
        ("purchases",),
        ("sales",),
        ("directories",),
        ("currencies",),
    ]
    assert isinstance(window.stack.currentWidget(), InventoryPage)  # it opens on the stock
    window.show_place(("journal",))  # Ctrl+1: the books are not shown
    window.new_document()  # Ctrl+N: no journal document
    assert isinstance(window.stack.currentWidget(), InventoryPage)
    assert ("journal",) not in window.pages
    assert "Ctrl+N" not in window.sidebar.hint.text()

    window.set_stock_only(False)  # the whole program again, from the company menu
    assert ("journal",) in places(window)
    assert window.session.stock_only is False


def test_purchase_hides_the_account_and_takes_goods_only(window):
    window.new_inventory_document("receipt")
    page = window.stack.currentWidget()
    assert isinstance(page, InventoryDocumentPage)
    model = page.model
    assert page.table.isColumnHidden(model.columns.index(ACCOUNT))
    assert model.rows[0].offset_account_id is not None  # put in by itself: 60
    header = Qt.Orientation.Horizontal
    assert model.headerData(model.columns.index(SC1), header) == "Поставщик"
    assert model.headerData(model.columns.index(ITEM), header) == "Товар"
    assert not page.btn_gl.isVisible()
    model.rows = [
        InventoryGridRow(memo="Доставка", offset_account_id=model.rows[0].offset_account_id)
    ]
    with pytest.raises(ValidationError, match="не указан товар"):
        model.to_inputs(complete=False)


def test_opening_stock_goes_against_retained_earnings(window):
    window.new_inventory_document("opening")
    page = window.stack.currentWidget()
    assert isinstance(page, InventoryDocumentPage)
    account = window.session.catalog.accounts[page.model.rows[0].offset_account_id]
    assert account.code == "88"  # not a supplier's account: nobody is owed for it


def test_landed_cost_hides_the_account_and_the_postings(window):
    window.new_inventory_document("landed_cost")
    page = window.stack.currentWidget()
    assert isinstance(page, LandedCostPage)
    charges = page.charges
    assert page.charges_table.isColumnHidden(charges.columns.index(CHARGE_ACCOUNT))
    column = charges.columns.index(CHARGE_SC1)
    assert charges.headerData(column, Qt.Orientation.Horizontal) == "Поставщик"
    assert not page.btn_from_gl.isVisible()
