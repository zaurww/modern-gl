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
