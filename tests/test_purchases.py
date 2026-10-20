"""«Поступление / Alış» of services and fixed assets: lines without an item.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPersistentModelIndex

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import QUANTITY_FACTOR, STANDARD_VAT_RATE, ReceiptLine
from modern_gl.desktop.inventory_document_page import (
    ACCOUNT,
    AMOUNT,
    ESC1,
    EXPENSE,
    ITEM,
    SC1,
    SC2,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from modern_gl.reporting.invoices import invoice_report
from tests.test_sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def values(shop: Shop, kind: str, *names: str) -> list[int]:
    kind_id = shop.ledger.subconto_kind_id(shop.company_id, kind)
    return [shop.ledger.add_subconto_value(shop.company_id, kind_id, name) for name in names]


def purchase(shop: Shop, lines: list[ReceiptLine], **kwargs) -> int:
    return shop.inventory.post_receipt(
        shop.company_id,
        "2026-03-05",
        lines,
        shop.acc["60"],
        shop.supplier,
        "Alış",
        vat_rate=STANDARD_VAT_RATE,
        **kwargs,
    )


def test_purchase_of_goods_a_service_and_a_fixed_asset(shop, conn):
    """One e-qaimə MT2603000111 from the supplier:
      5 printers      100.00 + VAT 18.00   Dt 41 [Printer, Əsas anbar] / Kt 60
      repair service   50.00 + VAT  9.00   Dt 26 [Təmir] / Kt 60
      laptop        1 000.00 + VAT 180.00  Dt 08 [Noutbuk] / Kt 60
      VAT 207.00 in one posting            Dt 19 [supplier] / Kt 60
    The supplier is owed 1 357.00 = 1 150.00 + 207.00; only the printers are in stock."""
    (repair,) = values(shop, "cost_item", "Təmir")
    (laptop,) = values(shop, "fixed_asset", "Noutbuk Dell")
    receipt = purchase(
        shop,
        [
            ReceiptLine(shop.item, shop.main, "5", "100", vat_amount="18"),
            ReceiptLine(
                None,
                None,
                None,
                "50",
                "Printerin təmiri",
                vat_amount="9",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            ),
            ReceiptLine(
                None,
                None,
                "1",
                "1000",
                "Noutbuk",
                vat_amount="180",
                expense_account_id=shop.acc["08"],
                expense_subconto=[laptop],
            ),
        ],
        invoice="MT2603000111",
    )
    assert shop.postings(receipt) == [
        ("41", "60", 10_000, "", "MT2603000111"),
        ("26", "60", 5_000, "Printerin təmiri", "MT2603000111"),
        ("08", "60", 100_000, "Noutbuk", "MT2603000111"),
        ("19", "60", 20_700, "НДС", "MT2603000111"),
    ]
    debits = conn.execute(
        "SELECT dt_sc1 FROM postings WHERE debit_account_id IN (?, ?) ORDER BY line_no",
        (shop.acc["26"], shop.acc["08"]),
    ).fetchall()
    assert [row[0] for row in debits] == [repair, laptop]
    (balance,) = stock_balances(conn, shop.company_id)
    assert (balance.quantity, balance.amount) == (5 * QUANTITY_FACTOR, 10_000)

    doc = shop.inventory.load_document(shop.company_id, receipt)
    service = doc.lines[1]
    assert (service.item_id, service.warehouse_id, service.quantity) == (None, None, 0)
    assert service.cost_account_id == shop.acc["26"]
    assert service.cost_subconto == (repair, None, None)
    assert doc.lines[2].quantity == QUANTITY_FACTOR

    (row,) = invoice_report(conn, shop.company_id, "2026-03-01", "2026-03-31")
    assert (row.credit, row.vat) == (135_700, 20_700)


def test_expense_line_is_checked_when_posted(shop):
    """A draft may lack the account; posting names it. The memo says what was bought."""
    draft = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-05",
        [ReceiptLine(None, None, None, "50", "Təmir")],
        shop.acc["60"],
        shop.supplier,
    )
    with pytest.raises(ValidationError, match="строка 1: не указан счёт затрат"):
        shop.inventory.post_document(shop.company_id, draft)
    shop.inventory.update_receipt_draft(
        shop.company_id,
        draft,
        "2026-03-05",
        [ReceiptLine(None, None, None, "50", expense_account_id=shop.acc["26"])],
        shop.acc["60"],
        shop.supplier,
    )
    with pytest.raises(ValidationError, match="укажите товар или что куплено"):
        shop.inventory.post_document(shop.company_id, draft)
    with pytest.raises(ValidationError, match="строка 1: не указан товар"):
        shop.inventory.post_receipt(
            shop.company_id,
            "2026-03-05",
            [ReceiptLine(None, None, None, "50", "Təmir", expense_account_id=shop.acc["26"])],
            shop.acc["60"],
            shop.supplier,
            opening=True,
        )


def test_expense_line_in_a_currency_receipt(shop, conn):
    """A service from abroad, 100.00 USD at 1.70: Dt 26 / Kt 60 170.00 (100.00 USD)."""
    usd = shop.ledger.currency_id(shop.company_id, "USD")
    (consulting,) = values(shop, "cost_item", "Konsaltinq")
    receipt = shop.inventory.post_receipt(
        shop.company_id,
        "2026-03-05",
        [
            ReceiptLine(
                None,
                None,
                None,
                None,
                "Konsaltinq",
                currency_amount="100",
                expense_account_id=shop.acc["26"],
                expense_subconto=[consulting],
            )
        ],
        shop.acc["60"],
        shop.supplier,
        currency_id=usd,
        currency_rate="1.7",
    )
    gl = shop.inventory.load_document(shop.company_id, receipt).gl_document_id
    posting = conn.execute("SELECT * FROM postings WHERE document_id = ?", (gl,)).fetchone()
    assert (posting["debit_account_id"], posting["amount"]) == (shop.acc["26"], 17_000)
    assert (posting["currency_id"], posting["currency_amount"]) == (usd, 10_000)


def test_receipt_page_buys_a_service(shop, conn, qtbot, monkeypatch):
    """A name that is no item becomes a service line: the expense account columns appear,
    the line posts Dt 26 [Təmir] / Kt 60 50.00 with VAT 9.00."""
    (repair,) = values(shop, "cost_item", "Təmir")
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    expense_column = model.columns.index(EXPENSE)
    assert page.table.isColumnHidden(expense_column)  # goods only so far

    monkeypatch.setattr(page, "_service_or_item", lambda text: "service")
    page._create_item(QPersistentModelIndex(model.index(0, 0)), "Printerin təmiri")
    assert not page.table.isColumnHidden(expense_column)
    assert page.table.currentIndex().column() == expense_column
    assert model.data(model.index(0, model.columns.index(ITEM))) == "Printerin təmiri"
    assert not model.flags(model.index(0, model.columns.index(WAREHOUSE)))

    def put(key: str, value) -> None:
        assert model.setData(model.index(0, model.columns.index(key)), value)

    put(EXPENSE, shop.acc["26"])
    assert not page.table.isColumnHidden(model.columns.index(ESC1))
    put(ESC1, repair)
    put(AMOUNT, 5_000)
    put(ACCOUNT, shop.acc["60"])
    put(SC1, shop.supplier[0])
    put(SC2, shop.supplier[1])
    assert model.rows[0].vat_amount == 900

    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("26", "60", 5_000), ("19", "60", 900)]
    assert page.model.rows[0].expense_subconto[0] == repair  # loaded back
    assert not page.table.isColumnHidden(expense_column)
