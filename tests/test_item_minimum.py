"""The minimum stock of an item: under it «Bu gün» says so, «Склад» shows the quantity
amber and offers a purchase of what is missing, up to the minimum, at the last price."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import SaleLine
from modern_gl.desktop.inventory_document_page import AMOUNT, QUANTITY, InventoryDocumentPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import below_minimum
from modern_gl.reporting.inventory.stock import items_below_minimum
from tests.test_sales import make_shop

Q = 10**6


def test_under_the_minimum_and_what_is_missing(conn, qtbot):
    """Bought 10 printers for 120.00, then 5 for 70.00 (14.00 each, the last price);
    sold 3 → 12 on hand, the minimum 15: 3 missing, a purchase of 3 × 14.00 = 42.00."""
    shop = make_shop(conn, "classic")
    shop.receipt("2026-01-10", "10", "120")
    shop.receipt("2026-01-12", "5", "70")
    shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "3", "60", "10.80")])
    assert below_minimum(conn, shop.company_id) == []
    shop.inventory.set_min_quantity(shop.company_id, shop.item, "15")
    (low,) = below_minimum(conn, shop.company_id)
    assert (low.quantity, low.minimum, low.missing) == (12 * Q, 15 * Q, 3 * Q)
    assert (low.last_price, low.warehouse_id) == (1_400, shop.main)
    (row,) = items_below_minimum(conn, shop.company_id, "2026-01-31")
    assert row.count == 1 and row.place == ("inventory",)
    assert below_minimum(conn, shop.company_id, "2026-01-11")[0].quantity == 10 * Q

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    stock = InventoryPage(session)
    qtbot.addWidget(stock)
    assert [m.item_id for m in stock.low] == [shop.item]
    purchase = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(purchase)
    purchase.fill_missing(stock.low)
    (line,) = purchase.model.rows
    assert (line.item_id, line.warehouse_id, line.quantity, line.amount) == (
        shop.item,
        shop.main,
        3 * Q,
        4_200,
    )
    assert purchase.model.columns.index(QUANTITY) < purchase.model.columns.index(AMOUNT)

    shop.inventory.set_min_quantity(shop.company_id, shop.item, "")  # no minimum again
    assert below_minimum(conn, shop.company_id) == []
    with pytest.raises((ValidationError, ValueError)):
        shop.inventory.set_min_quantity(shop.company_id, shop.item, "-1")
