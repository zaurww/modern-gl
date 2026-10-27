"""«Вид» of a purchase line: goods (an item, a warehouse) or a service (an account).
An e-qaimə's lines that no item or earlier purchase names come as services; «Товар»
makes them new items at once.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QLineEdit

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ITEM,
    QUANTITY,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.inventory_document_page.columns import GOODS, KIND, SERVICE
from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
from modern_gl.desktop.session import Session
from modern_gl.reporting.inventory import item_choices, stock_balances
from tests.test_sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def items_named(shop: Shop) -> dict[str, int]:
    return {c.label: c.id for c in item_choices(shop.ledger.conn, shop.company_id)}


def test_named_items_are_added_once(shop):
    """«Printer» is an item already; «Zebra» twice (in another case) is one new item."""
    unit = shop.ledger.conn.execute(
        "SELECT unit_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()["unit_id"]
    account = shop.acc["41"]
    zebra, printer, again = shop.inventory.add_named_items(
        shop.company_id, ["Zebra", "printer", "ZEBRA "], unit, account
    )
    assert printer == shop.item
    assert zebra == again
    assert set(items_named(shop)) == {"Printer", "Zebra"}


def receipt_with_services(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    """A purchase as an e-qaimə comes: two lines no item names, each a service."""
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    for row, (name, quantity, amount) in enumerate(
        [("Zebra DS2208 Scanner", 1_000_000, 14_000), ("Xprinter XP-Q80A", 3_000_000, 18_000)]
    ):
        if row:
            model.insert_row()
        page._make_service(row, name)
        model.setData(model.index(row, model.columns.index(QUANTITY)), quantity)
        model.setData(model.index(row, model.columns.index(AMOUNT)), amount)
    return page


def test_service_lines_become_goods(shop, conn, qtbot, monkeypatch):
    """«Товар» in «Вид» of the first line: both lines (no account chosen for either)
    become new items, onto the only warehouse «Əsas anbar», and post to stock:
    Dt 41 / Kt 60 140.00 and 180.00, VAT 18% 25.20 + 32.40 = 57.60 in Dt 19 / Kt 60;
    the scanner is 1 in stock for 140.00, the printers 3 for 180.00."""
    page = receipt_with_services(shop, conn, qtbot)
    model = page.model
    kind = model.columns.index(KIND)
    assert not page.table.isColumnHidden(kind)
    assert model.data(model.index(0, kind)) == "Счёт"

    asked = []

    def accept(dialog: NewNamesDialog):
        asked.append(dialog.checked_rows())
        dialog.account.setCurrentIndex(dialog.account.findData(shop.acc["41"]))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewNamesDialog, "exec", accept)
    assert model.setData(model.index(0, kind), GOODS)
    assert model.rows[0].item_id is None  # the page makes the item
    page._make_goods(0)
    assert asked == [[0, 1]]

    items = items_named(shop)
    assert [row.item_id for row in model.rows] == [
        items["Zebra DS2208 Scanner"],
        items["Xprinter XP-Q80A"],
    ]
    assert [row.warehouse_id for row in model.rows] == [shop.main, shop.main]
    assert model.data(model.index(0, kind)) == "Склад"
    assert page.table.isColumnHidden(kind)  # no service left to change

    model.set_party(shop.acc["60"], [*shop.supplier, None])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert sorted(p[:3] for p in shop.postings(page.doc.id)) == [
        ("19", "60", 5_760),
        ("41", "60", 14_000),
        ("41", "60", 18_000),
    ]
    stock = {
        b.item_id: (b.quantity, b.amount)
        for b in stock_balances(conn, shop.company_id, "2099-12-31")
    }
    assert stock[items["Zebra DS2208 Scanner"]] == (1_000_000, 14_000)
    assert stock[items["Xprinter XP-Q80A"]] == (3_000_000, 18_000)


def test_goods_line_becomes_a_service(shop, conn, qtbot):
    """«Услуга» in «Вид» of a printer line: no item and no warehouse, the item's name
    stays as what the service is."""
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    model.setData(model.index(0, model.columns.index(ITEM)), shop.item)
    model.setData(model.index(0, model.columns.index(WAREHOUSE)), shop.main)
    assert model.setData(model.index(0, model.columns.index(KIND)), SERVICE)
    row = model.rows[0]
    assert (row.item_id, row.warehouse_id, row.memo) == (None, None, "Printer")
    assert model.is_service(0)


def test_adding_a_name_on_a_service_line_asks_for_an_item(shop, conn, qtbot, monkeypatch):
    """«+ Добавить «…»» picked in the name of a service line asks for a new item; a name
    typed there without it only corrects what the service is."""
    page = receipt_with_services(shop, conn, qtbot)
    monkeypatch.setattr(page, "_create_item", lambda index, text: None)  # its questions
    model = page.model
    delegate = page.delegate
    asked = []
    delegate.unknown_item.connect(lambda index, text: asked.append(text))
    index = model.index(0, model.columns.index(ITEM))
    editor = QLineEdit("Zebra DS2208-SR")
    delegate.setModelData(editor, model, index)
    assert (asked, model.rows[0].memo) == ([], "Zebra DS2208-SR")
    editor = QLineEdit("Zebra DS2208-SR")
    editor.setProperty("gl_add", True)
    delegate.setModelData(editor, model, index)
    assert asked == ["Zebra DS2208-SR"]


def test_the_kind_cell_opens_with_both_choices(shop, conn, qtbot):
    """The cell of «Вид» opens empty: its list is not narrowed to what the line is now,
    «Товар» is there to pick without deleting «Услуга» first."""
    page = receipt_with_services(shop, conn, qtbot)
    model = page.model
    index = model.index(0, model.columns.index(KIND))
    editor = page.delegate.createEditor(page.table.viewport(), None, index)
    page.delegate.setEditorData(editor, index)
    assert editor.text() == ""
    page.delegate.setModelData(editor, model, index)  # Enter on it: nothing changes
    assert model.is_service(0)
