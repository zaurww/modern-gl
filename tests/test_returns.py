"""Returns: goods back to the supplier, goods back from a customer — posted the other way
round from the purchase and the sale, with the return e-qaimə's number. The numbers are
worked out by hand in `shop`'s docstring and in each test."""

from __future__ import annotations

import pytest

from modern_gl.application.book_invoices import book_invoices
from modern_gl.application.catalog import Catalog
from modern_gl.application.eqaime import import_drafts, parse_invoice, plan_import
from modern_gl.application.inventory import (
    PURCHASE_RETURN,
    QUANTITY_FACTOR,
    SALE_RETURN,
    ReturnLine,
    SaleLine,
)
from modern_gl.desktop.inventory_document_page import PRICE, QUANTITY, InventoryDocumentPage
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from modern_gl.reporting.trade import PURCHASE, trade_documents
from tests.test_sales import Shop, make_shop

Q = QUANTITY_FACTOR


@pytest.fixture
def shop(conn) -> Shop:
    """Classic chart, ƏDV 18%:
    10.01 bought 10 printers for 120.00 (12.00 each)
    15.01 bought 10 for 140.00 (14.00 each) → 20 for 260.00, 13.00 each
    """
    shop = make_shop(conn, "classic")
    shop.receipt("2026-01-10", "10", "120")
    shop.receipt("2026-01-15", "10", "140")
    return shop


def first_line(shop: Shop, document_id: int) -> int:
    return shop.inventory.load_document(shop.company_id, document_id).lines[0].id


def balance(shop: Shop) -> tuple[int, int]:
    (b,) = stock_balances(shop.ledger.conn, shop.company_id)
    return b.quantity // Q, b.amount


def to_supplier(shop: Shop, quantity: str, amount: str, vat: str, **kwargs) -> int:
    return shop.inventory.post_return(
        shop.company_id,
        "2026-01-20",
        PURCHASE_RETURN,
        [ReturnLine(shop.item, shop.main, quantity, amount, vat, **kwargs)],
        shop.acc["60"],
        shop.supplier,
        vat_rate=1800,
        invoice="RT0001",
    )


def test_goods_back_to_the_supplier(shop):
    """2 printers of the first purchase back at its price 12.00 = 24.00 + ƏDV 4.32; they
    leave at the average 13.00 = 26.00, the 2.00 below the cost is other expense:
      60 / 41    24.00   Printer
      80 / 41     2.00   Разница цены возврата
      60 / 19     4.32   НДС
    18 printers for 234.00 left. On the portal the buyer sends the return e-qaimə: the books
    see RT0001 among the sent ones — 28.32 with ƏDV 4.32."""
    purchase = shop.inventory.load_document(shop.company_id, 1)
    returned = purchase.lines[0].id
    doc = to_supplier(shop, "2", "24", "4.32", returned_line_id=returned)
    assert shop.postings(doc) == [
        ("60", "41", 2_400, "Printer", "RT0001"),
        ("80", "41", 200, "Разница цены возврата", None),
        ("60", "19", 432, "НДС", "RT0001"),
    ]
    assert balance(shop) == (18, 23_400)
    sent = book_invoices(shop.ledger.conn, shop.company_id, outgoing=True)["RT0001"]
    assert (sent.total, sent.vat) == (2_832, 432)
    assert "RT0001" not in book_invoices(shop.ledger.conn, shop.company_id, outgoing=False)
    assert shop.inventory.returnable(shop.company_id, returned) == 8 * Q
    loaded = shop.inventory.load_document(shop.company_id, doc)
    assert loaded.doc_type == PURCHASE_RETURN and loaded.lines[0].returned_line_id == returned


def test_no_more_back_than_was_bought_and_the_purchase_stays(shop):
    """8 of the first purchase are left to return; its line cannot go while a return
    names it."""
    returned = first_line(shop, 1)
    to_supplier(shop, "2", "24", "4.32", returned_line_id=returned)
    with pytest.raises(ValidationError, match="не больше 8"):
        to_supplier(shop, "9", "108", "19.44", returned_line_id=returned)
    with pytest.raises(ValidationError, match="возврат №3"):
        shop.inventory.delete_document(shop.company_id, 1)


def test_goods_back_from_a_customer_at_the_cost_of_their_sale(shop):
    """25.01 sold 3 for 60.00 + 10.80 at the average 13.00 = 39.00 (17 for 221.00 left);
    28.01 bought 5 for 80.00 → 22 for 301.00. 30.01 one comes back from that sale at
    20.00 + ƏDV 3.60: the revenue and the ƏDV go back (ƏDV is charged from 46 in the
    classic chart), the printer comes back at its sale's cost 39.00 / 3 = 13.00:
      46 / 62     23.60   Printer
      41 / 46     13.00   Printer
      68.2 / 46    3.60   НДС
    23 for 314.00. The customer sends the return e-qaimə: RT0002 is among the received."""
    sale = shop.sale("2026-01-25", [SaleLine(shop.item, shop.main, "3", "60", "10.80")])
    shop.receipt("2026-01-28", "5", "80")
    doc = shop.inventory.post_return(
        shop.company_id,
        "2026-01-30",
        SALE_RETURN,
        [
            ReturnLine(
                shop.item, shop.main, "1", "20", "3.60", returned_line_id=first_line(shop, sale)
            )
        ],
        shop.acc["62"],
        [shop.customer, shop.contract],
        vat_rate=1800,
        invoice="RT0002",
    )
    assert shop.postings(doc) == [
        ("46", "62", 2_360, "Printer", "RT0002"),
        ("41", "46", 1_300, "Printer", None),
        ("68.2", "46", 360, "НДС", "RT0002"),
    ]
    assert balance(shop) == (23, 31_400)
    received = book_invoices(shop.ledger.conn, shop.company_id, outgoing=False)["RT0002"]
    assert (received.total, received.vat) == (2_360, 360)


def test_a_return_without_its_sale_takes_the_average_and_is_recalculated(shop):
    """Without the sale named the printer comes back at the warehouse's average that day:
    260.00 / 20 = 13.00. A purchase entered later but dated before (12.01, 10 for 100.00)
    makes the average 360.00 / 30 = 12.00: the return is posted again at 12.00 by itself."""
    doc = shop.inventory.post_return(
        shop.company_id,
        "2026-01-30",
        SALE_RETURN,
        [ReturnLine(shop.item, shop.main, "1", "20", "3.60")],
        shop.acc["62"],
        [shop.customer, shop.contract],
        vat_rate=1800,
    )
    assert shop.inventory.load_document(shop.company_id, doc).lines[0].inventory_amount == 1_300
    shop.receipt("2026-01-12", "10", "100")
    assert shop.inventory.load_document(shop.company_id, doc).lines[0].inventory_amount == 1_200
    assert balance(shop) == (31, 37_200)


def test_the_return_is_filled_from_its_purchase(shop, conn, qtbot):
    """«Оформить возврат» on the first purchase (without ƏDV): its 10 printers at 120.00,
    the supplier in the header. 3 go back at its price 12.00 = 36.00; they leave at the
    average 13.00, 3.00 below the cost is other expense. The purchases list shows it as a
    return, negative."""

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    purchase = InventoryDocumentPage(session, 1)
    qtbot.addWidget(purchase)
    assert purchase.btn_return.isVisibleTo(purchase)
    page = InventoryDocumentPage(session, doc_type=PURCHASE_RETURN)
    qtbot.addWidget(page)
    assert page.fill_return_of(1)
    (row,) = page.model.rows
    assert (row.quantity, row.amount, row.returned_line_id) == (10 * Q, 12_000, first_line(shop, 1))
    assert page.party.currentData() == shop.supplier[0]
    model = page.model
    model.setData(model.index(0, model.columns.index(QUANTITY)), 3 * Q)
    model.setData(model.index(0, model.columns.index(PRICE)), 1_200)  # the price stays 12.00
    page.invoice.setText("RT0003")
    assert page.save(post=True), page.error.text()
    assert [p[:3] for p in shop.postings(page.doc.id)] == [
        ("60", "41", 3_600),
        ("80", "41", 300),
    ]
    listed = trade_documents(conn, shop.company_id, PURCHASE)[0]
    assert listed.is_return and (listed.amount, listed.vat) == (-3_600, 0)


def test_a_customers_return_e_qaime_becomes_a_return_draft(shop, conn):
    """Alfa sends the return e-qaimə for 1 printer (20.00, ƏDV base 20.00 → 3.60): the
    import makes a return from the customer on its account 62, the printer found by the
    sale to Alfa; a return of services is not imported."""
    shop.ledger.set_subconto_value_tax(shop.company_id, shop.customer, "1234567891")
    shop.sale("2026-01-25", [SaleLine(shop.item, shop.main, "3", "60", "10.80", "Printer")])
    row = {
        "id": "r1",
        "serialNumber": "RT2601000001",
        "status": "approved",
        "kind": "returnInvoice",
        "createdAt": "2026-01-30T10:00:00",
        "sender": {"tin": "1234567891", "name": "Alfa"},
    }
    item = {"productName": "Printer", "productGroup": {"code": "8443"}, "quantity": 1}
    detail = {**row, "items": [{**item, "cost": 20, "vat18": 20}]}
    service = {**row, "id": "r2", "serialNumber": "RT2601000002"}
    service_detail = {
        **service,
        "items": [{**item, "productGroup": {"code": "9995"}, "cost": 5, "vat18": 5}],
    }
    plans = plan_import(
        conn,
        shop.company_id,
        [
            parse_invoice(row, detail, outgoing=False),
            parse_invoice(service, service_detail, outgoing=False),
        ],
    )
    assert plans[0].return_type == SALE_RETURN and plans[0].lines[0].item_id == shop.item
    assert not plans[1].importable
    (draft,) = import_drafts(shop.inventory, shop.company_id, plans)
    doc = shop.inventory.load_document(shop.company_id, draft)
    (line,) = doc.lines
    assert (doc.doc_type, doc.invoice) == (SALE_RETURN, "RT2601000001")
    assert (line.amount, line.vat_amount, line.offset_account_id) == (2_000, 360, shop.acc["62"])
    assert line.offset_subconto[0] == shop.customer
