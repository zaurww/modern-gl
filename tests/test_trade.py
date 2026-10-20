"""«Покупки и продажи / Alış və satış»: purchases and sales in one list."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine, SaleLine
from modern_gl.desktop.session import Session
from modern_gl.desktop.trade_page import TradePage
from modern_gl.reporting.trade import PURCHASE, SALE, trade_documents
from tests.test_sales import Shop, make_shop


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
    assert [(r.id, r.doc_type) for r in rows] == [(draft, SALE), (sale, SALE), (purchase, PURCHASE)]
    by_id = {r.id: r for r in rows}
    assert (by_id[sale].amount, by_id[sale].vat, by_id[sale].total) == (6_000, 1_080, 7_080)
    assert (by_id[sale].counterparties, by_id[sale].tax_ids) == ("Alfa", "1234567891")
    assert by_id[sale].invoice == "MT2601001"
    assert by_id[purchase].counterparties == "Təchizatçı"
    assert (by_id[draft].status, by_id[draft].total) == ("draft", 2_500)
    assert [r.id for r in trade_documents(conn, shop.company_id, PURCHASE)] == [purchase]


def test_trade_page_filters_searches_and_opens(shop, conn, qtbot):
    purchase, sale, _ = fill(shop)
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = TradePage(session)
    qtbot.addWidget(page)
    assert len(page.model.rows) == 3
    # posted only: a purchase of 141.60, a sale of 70.80
    assert page.footer.text() == "Проведено: покупки 141.60   ·   продажи 70.80"

    page.kind.setCurrentIndex(page.kind.findData(PURCHASE))
    page.refresh()
    assert [r.id for r in page.model.rows] == [purchase]
    page.kind.setCurrentIndex(0)
    page.search.setText("12345")  # the customer's VÖEN
    assert {r.id for r in page.model.rows} >= {sale}
    assert purchase not in {r.id for r in page.model.rows}

    with qtbot.waitSignal(page.open_inventory_document) as opened:
        page.drill(page.model.rows[0])
    assert opened.args == [page.model.rows[0].id]
    with qtbot.waitSignal(page.new_inventory_document) as new:
        page.header.action_row.itemAt(3).widget().click()  # «+ Продажа»
    assert new.args == [SALE]


def test_warehouse_list_leaves_out_trade_without_goods(shop, conn):
    """The sale draft of a service only is not a warehouse document."""
    from modern_gl.reporting.inventory import list_inventory_documents

    purchase, sale, draft = fill(shop)
    listed = [d.id for d in list_inventory_documents(conn, shop.company_id)]
    assert purchase in listed and sale in listed and draft not in listed
