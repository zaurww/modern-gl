"""A sale typed before its goods' purchase (the goods came, the papers did not): no stock
below zero — the sale stays a draft and offers to bring the missing goods in as a
purchase «ждёт e-qaimə» at the last price; posted, it lets the sale go."""

from __future__ import annotations

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ITEM,
    QUANTITY,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session
from tests.test_sales import Shop, make_shop

Q = 10**6


def sale_page(shop: Shop, conn, qtbot, quantity: int) -> InventoryDocumentPage:
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="sale")
    qtbot.addWidget(page)
    page.party.setCurrentIndex(page.party.findData(shop.customer))
    page._party_chosen()
    model = page.model
    for key, value in (
        (ITEM, shop.item),
        (WAREHOUSE, shop.main),
        (QUANTITY, quantity * Q),
        (AMOUNT, 6_000),
    ):
        model.setData(model.index(0, model.columns.index(key)), value)
    return page


def documents(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM inventory_documents").fetchone()[0]


def test_a_sale_that_does_not_post_stays_one_draft(conn, qtbot):
    """Was: each «Провести» that failed left one more draft behind the page."""
    shop = make_shop(conn, "classic")
    page = sale_page(shop, conn, qtbot, 3)
    assert not page.save(post=True)
    assert "недостаточно товара" in page.error.text()
    assert not page.save(post=True)
    assert documents(conn) == 1
    assert page.doc is not None and page.doc.status == "draft"


def test_the_missing_goods_come_in_as_a_purchase_awaiting_its_e_qaime(conn, qtbot):
    """10 printers bought for 120.00 (10.01, 12.00 each); 12 sold on 25.01 — 2 are not
    there yet. «Оприходовать недостающее»: a purchase dated 25.01, 2 at the last price
    12.00 = 24.00 from the same supplier, waiting for its e-qaimə. Posted, the sale posts:
    12 at 12.00 = 144.00 of cost, nothing left."""
    shop = make_shop(conn, "classic")
    shop.receipt("2026-01-10", "10", "120")
    sale = sale_page(shop, conn, qtbot, 12)
    sale.date.setDate(sale.date.date().fromString("25.01.2026", "dd.MM.yyyy"))
    assert not sale.save(post=True)
    assert sale.btn_shortage.isVisibleTo(sale)
    purchase = InventoryDocumentPage(sale.s, doc_type="receipt")
    qtbot.addWidget(purchase)
    assert purchase.fill_shortage(sale.doc.id)
    (line,) = purchase.model.rows
    assert (line.item_id, line.warehouse_id, line.quantity, line.amount) == (
        shop.item,
        shop.main,
        2 * Q,
        2_400,
    )
    assert line.offset_subconto[0] == shop.supplier[0]
    assert purchase._awaits() and purchase.date.date().toString("dd.MM.yyyy") == "25.01.2026"
    assert purchase.save(post=True), purchase.error.text()
    assert purchase.doc.awaits_invoice
    assert sale.save(post=True), sale.error.text()
    (goods,) = [p for p in shop.postings(sale.doc.id) if p[:2] == ("46", "41")]
    assert goods[2] == 14_400
