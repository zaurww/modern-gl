"""«Покупки / Alış» and «Продажи / Satış»: two sections, each its own list (D46)."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine, SaleLine
from modern_gl.desktop.session import Session
from modern_gl.desktop.trade_page import TradePage
from modern_gl.reporting.trade import PURCHASE, SALE, trade_documents
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    shop = make_shop(conn, "classic")
    shop.ledger.set_subconto_value_tax(shop.company_id, shop.customer, "1234567891")
    return shop


def fill(shop: Shop) -> tuple[int, int, int]:
    """A purchase 10 printers 120.00 + VAT 21.60, a sale 3 for 60.00 + VAT 10.80 (Alfa,
    MT2601001) and a sale draft of a service 25.00 without VAT."""
    purchase = shop.inventory.post_receipt(
        shop.company_id,
        "2026-01-10",
        [ReceiptLine(shop.item, shop.main, "10", "120", vat_amount="21.60")],
        shop.acc["60"],
        shop.supplier,
        vat_rate=STANDARD_VAT_RATE,
    )
    sale = shop.sale(
        "2026-01-20", [SaleLine(shop.item, shop.main, "3", "60", "10.80")], invoice="MT2601001"
    )
    draft = shop.inventory.create_sale_draft(
        shop.company_id,
        "2026-01-21",
        [SaleLine(None, None, None, "25", memo="Çatdırılma")],
        shop.acc["62"],
        [shop.customer, shop.contract],
    )
    return purchase, sale, draft


def test_trade_documents_lists_purchases_and_sales(shop, conn):
    purchase, sale, draft = fill(shop)
    rows = trade_documents(conn, shop.company_id)
    # oldest first: they are checked one by one from the top (the e-qaimə of a month)
    assert [(r.id, r.doc_type) for r in rows] == [(purchase, PURCHASE), (sale, SALE), (draft, SALE)]
    by_id = {r.id: r for r in rows}
    assert (by_id[sale].amount, by_id[sale].vat, by_id[sale].total) == (6_000, 1_080, 7_080)
    assert (by_id[sale].counterparties, by_id[sale].tax_ids) == ("Alfa", "1234567891")
    assert by_id[sale].invoice == "MT2601001"
    assert by_id[purchase].counterparties == "Təchizatçı"
    assert (by_id[draft].status, by_id[draft].total) == ("draft", 2_500)
    assert [r.id for r in trade_documents(conn, shop.company_id, PURCHASE)] == [purchase]


def test_trade_documents_limit_keeps_the_newest_oldest_first(shop, conn):
    """Of more documents than shown, the latest are kept — and still listed from the top."""
    _purchase, sale, draft = fill(shop)
    rows = trade_documents(conn, shop.company_id, limit=2)
    assert [r.id for r in rows] == [sale, draft]


def test_purchases_and_sales_are_separate_pages(shop, conn, qtbot):
    purchase, sale, draft = fill(shop)
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    purchases, sales = TradePage(session, PURCHASE), TradePage(session, SALE)
    qtbot.addWidget(purchases)
    qtbot.addWidget(sales)
    assert purchases.key == ("purchases",) and sales.key == ("sales",)
    assert [r.id for r in purchases.model.rows] == [purchase]
    assert [r.id for r in sales.model.rows] == [sale, draft]
    # posted only: the purchase 120.00 + 21.60, the sale 60.00 + 10.80 (the draft is not)
    assert purchases.footer.text() == "Проведено покупок: 141.60"
    assert sales.footer.text() == "Проведено продаж: 70.80"

    sales.search.setText("12345")  # the customer's VÖEN: the sale and the draft
    assert [r.id for r in sales.model.rows] == [sale, draft]
    sales.search.setText("MT2601001")
    assert [r.id for r in sales.model.rows] == [sale]
    purchases.search.setText("12345")
    assert purchases.model.rows == []
    sales.search.setText("")

    with qtbot.waitSignal(sales.open_inventory_document) as opened:
        sales.drill(sales.model.rows[0])
    assert opened.args == [sale]
    with qtbot.waitSignal(purchases.new_inventory_document) as new:
        purchases.new_button.click()
    assert new.args == [PURCHASE]
    with qtbot.waitSignal(sales.new_inventory_document) as new:
        sales.new_button.click()
    assert new.args == [SALE]


def test_trade_page_keeps_the_cursor_on_refresh(shop, conn, qtbot):
    """Checked one by one: back from a document the list is read again — the cursor stays
    on it, so Down goes to the next one."""
    _purchase, _sale, draft = fill(shop)
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    sales = TradePage(session, SALE)
    qtbot.addWidget(sales)
    sales.table.setCurrentIndex(sales.model.index(1, 2))
    sales.refresh()
    assert sales.table.currentIndex().row() == 1
    assert sales.table.currentIndex().column() == 2
    assert sales.model.rows[1].id == draft


def test_warehouse_list_leaves_out_trade_without_goods(shop, conn):
    """The sale draft of a service only is not a warehouse document."""
    from modern_gl.reporting.inventory import list_inventory_documents

    purchase, sale, _draft = fill(shop)
    listed = [d.id for d in list_inventory_documents(conn, shop.company_id)]
    assert listed == [purchase, sale]  # oldest first; the service draft is not here
    assert [d.id for d in list_inventory_documents(conn, shop.company_id, limit=1)] == [sale]
