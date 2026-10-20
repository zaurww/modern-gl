"""Receipts and batch charges in a currency; the batch cost report (D33, stage 4)."""

from dataclasses import dataclass
from datetime import date

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    Inventory,
    LandedCostCharge,
    LandedCostTarget,
    ReceiptLine,
)
from modern_gl.application.ledger import Ledger
from modern_gl.desktop import landed_cost_page as lc
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    CURRENCY_AMOUNT,
    PRICE,
    InventoryDocumentPage,
    InventoryGridRow,
)
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import CURRENCY_OPTIONAL
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import batch_cost, receipt_line_choices, stock_balances


@dataclass
class Import:
    inventory: Inventory
    ledger: Ledger
    company_id: int
    usd: int
    item_a: int
    item_b: int
    main: int
    stock: int  # 41
    foreign: int  # 60.2: suppliers, in manat or in a currency
    supplier: int


@pytest.fixture
def imp(ledger, conn) -> Import:
    cid = ledger.create_company("Импорт")
    item_kind = ledger.add_subconto_kind(cid, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    counterparty = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    stock = ledger.add_account(
        cid, "41", "Товары", subconto=[item_kind, warehouse_kind], account_class="asset"
    )
    foreign = ledger.add_account(
        cid,
        "60.2",
        "Иностранные поставщики",
        subconto=[counterparty],
        account_class="liability",
        currency=CURRENCY_OPTIONAL,
    )
    supplier = ledger.add_subconto_value(cid, counterparty, "Supplier GmbH")
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "шт", "Штука")
    return Import(
        inventory,
        ledger,
        cid,
        ledger.currency_id(cid, "USD"),
        inventory.add_item(cid, "Товар A", unit, stock),
        inventory.add_item(cid, "Товар B", unit, stock),
        inventory.add_warehouse(cid, "Основной"),
        stock,
        foreign,
        supplier,
    )


def usd_receipt(m: Import, lines, rate="1.7", **kwargs) -> int:
    return m.inventory.post_receipt(
        m.company_id,
        "2026-04-01",
        lines,
        m.foreign,
        [m.supplier],
        "Инвойс 15",
        currency_id=m.usd,
        currency_rate=rate,
        **kwargs,
    )


def gl_postings(conn, m: Import, inv_doc: int) -> list[tuple]:
    gl_id = m.inventory.load_document(m.company_id, inv_doc).gl_document_id
    return [
        (r["credit_account_id"], r["amount"], r["currency_id"], r["currency_amount"])
        for r in conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl_id,)
        )
    ]


def test_receipt_in_usd_is_valued_at_the_rate(imp, conn):
    """100.00 USD and 33.33 USD at 1.7: 170.00 and 56.661 -> 56.66 manat; the supplier's
    postings keep the dollars."""
    m = imp
    doc = usd_receipt(
        m,
        [
            ReceiptLine(m.item_a, m.main, "10", None, currency_amount="100"),
            ReceiptLine(m.item_b, m.main, "3", None, currency_amount="33.33"),
        ],
    )
    loaded = m.inventory.load_document(m.company_id, doc)
    assert (loaded.currency_id, loaded.currency_rate) == (m.usd, 1_700_000)
    assert [(line.currency_amount, line.amount) for line in loaded.lines] == [
        (10_000, 17_000),
        (3_333, 5_666),
    ]
    assert gl_postings(conn, m, doc) == [
        (m.foreign, 17_000, m.usd, 10_000),
        (m.foreign, 5_666, m.usd, 3_333),
    ]
    assert sum(b.amount for b in stock_balances(conn, m.company_id)) == 22_666


def test_currency_receipt_rules(imp):
    m = imp
    line = ReceiptLine(m.item_a, m.main, "1", None, currency_amount="10")
    with pytest.raises(ValidationError, match="не указан курс"):
        usd_receipt(m, [line], rate=None)
    with pytest.raises(ValidationError, match="НДС не указывается"):
        usd_receipt(
            m,
            [ReceiptLine(m.item_a, m.main, "1", None, vat_amount="1", currency_amount="10")],
            vat_rate=1800,
        )
    with pytest.raises(ValidationError, match="только поступление"):
        m.inventory.post_receipt(
            m.company_id,
            "2026-01-01",
            [line],
            m.foreign,
            [m.supplier],
            opening=True,
            currency_id=m.usd,
            currency_rate="1.7",
        )


def test_editing_the_rate_revalues_a_posted_receipt(imp, conn):
    m = imp
    doc = usd_receipt(m, [ReceiptLine(m.item_a, m.main, "10", None, currency_amount="100")])
    line = m.inventory.load_document(m.company_id, doc).lines[0]
    with m.inventory.reposting(m.company_id, doc):
        m.inventory.update_receipt_draft(
            m.company_id,
            doc,
            "2026-04-01",
            [ReceiptLine(m.item_a, m.main, "10", None, currency_amount="100", line_id=line.id)],
            m.foreign,
            [m.supplier],
            currency_id=m.usd,
            currency_rate="1.7015",  # the customs rate
        )
    assert m.inventory.load_document(m.company_id, doc).lines[0].amount == 17_015
    assert gl_postings(conn, m, doc) == [(m.foreign, 17_015, m.usd, 10_000)]


def batch(m: Import, charges) -> tuple[int, int, int]:
    doc = usd_receipt(
        m,
        [
            ReceiptLine(m.item_a, m.main, "10", None, currency_amount="100"),  # 170.00
            ReceiptLine(m.item_b, m.main, "5", None, currency_amount="50"),  # 85.00
        ],
    )
    a, b = (line.id for line in m.inventory.load_document(m.company_id, doc).lines)
    lc = m.inventory.create_landed_cost_draft(
        m.company_id,
        "2026-04-03",
        [LandedCostTarget(a), LandedCostTarget(b)],
        charges,
        "value",
        "Партия 15",
    )
    m.inventory.post_document(m.company_id, lc)
    return lc, a, b


def freight_usd(m: Import, amount="30", **kwargs) -> LandedCostCharge:
    return LandedCostCharge(
        None,
        m.foreign,
        [m.supplier],
        currency_id=m.usd,
        currency_rate="1.7",
        currency_amount=amount,
        memo="Фрахт",
        **kwargs,
    )


def test_charge_in_usd_keeps_its_dollars_on_every_posting(imp, conn):
    """Freight 30.00 USD at 1.7 = 51.00, by value 170 : 85 -> A 34.00, B 17.00; the
    dollars follow: A 20.00 USD, B 10.00 USD."""
    m = imp
    lc, _, _ = batch(m, [freight_usd(m)])
    charge = m.inventory.load_document(m.company_id, lc).charges[0]
    assert (charge.amount, charge.currency_amount, charge.currency_rate) == (
        5_100,
        3_000,
        1_700_000,
    )
    assert gl_postings(conn, m, lc) == [
        (m.foreign, 3_400, m.usd, 2_000),
        (m.foreign, 1_700, m.usd, 1_000),
    ]


def test_charge_in_currency_rules(imp):
    m = imp
    with pytest.raises(ValidationError, match="НДС не указывается"):
        batch(m, [freight_usd(m, vat_amount="5")])


def test_batch_cost_report(imp, conn):
    """A: 100 USD at 1.7 = 170.00 + freight 34.00 + customs 20.00 = 224.00, 22.40 a piece;
    B: 85.00 + 17.00 + 10.00 = 112.00. Customs 30.00 manat by value 170 : 85 -> 20 : 10."""
    m = imp
    customs_type = m.inventory.add_landed_cost_type(m.company_id, "Таможня")
    customs = LandedCostCharge("30", m.foreign, [m.supplier], cost_type_id=customs_type)
    lc, _, _ = batch(m, [freight_usd(m), customs])
    charges, lines = batch_cost(conn, m.company_id, lc)
    assert [(c.title, c.amount, c.currency, c.currency_amount) for c in charges] == [
        ("Фрахт", 5_100, "USD", 3_000),
        ("Таможня", 3_000, None, None),
    ]
    first, second = lines
    assert (first.currency, first.currency_amount, first.rate, first.cost) == (
        "USD",
        10_000,
        1_700_000,
        17_000,
    )
    assert first.shares == {charges[0].id: 3_400, charges[1].id: 2_000}
    assert (first.total, second.total) == (22_400, 11_200)
    assert sum(b.amount for b in stock_balances(conn, m.company_id)) == 33_600


# ---- the receipt page ------------------------------------------------------------------


def receipt_page(m: Import, conn, qtbot) -> InventoryDocumentPage:
    session = Session(
        conn,
        m.ledger,
        m.company_id,
        "Импорт",
        Catalog(conn, m.company_id),
        working_date=date(2026, 4, 1),
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    return page


def test_receipt_page_in_usd(imp, conn, qtbot):
    m = imp
    m.ledger.set_rate(m.company_id, "USD", "2026-03-31", 1_700_000)
    page = receipt_page(m, conn, qtbot)
    assert not page.is_dirty()
    model = page.model
    column = model.columns.index(CURRENCY_AMOUNT)
    assert page.table.isColumnHidden(column)  # manat until a currency is chosen

    page.currency.setCurrentIndex(page.currency.findData(m.usd))
    page._currency_changed()
    assert page.rate.text() == "1.7000"  # the rate of the day
    assert not page.table.isColumnHidden(column)
    assert page._chosen_vat_rate() is None and not page.vat_rate.isEnabled()
    model.rows[0] = InventoryGridRow(
        m.item_a,
        m.main,
        quantity=10 * QUANTITY_FACTOR,
        offset_account_id=m.foreign,
        offset_subconto=[m.supplier, None, None],
    )
    model.setData(model.index(0, column), 10_000)  # 100.00 USD
    assert model.rows[0].amount == 17_000
    assert not model.editable(AMOUNT)  # the manat amount follows the rate
    price = model.index(0, model.columns.index(PRICE))
    assert price.data() == "10.00"  # the price in dollars

    page.rate.setText("1.7015")  # the customs rate
    page._rate_edited()
    assert model.rows[0].amount == 17_015
    assert page.currency_total.text() == "100.00 USD"
    assert page.total.text() == "170.15"

    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert (page.doc.currency_id, page.doc.currency_rate) == (m.usd, 1_701_500)
    assert page.rate.text() == "1.7015" and page.rate_typed
    assert sum(b.amount for b in stock_balances(conn, m.company_id)) == 17_015


def test_batch_page_takes_a_charge_in_usd_and_shows_the_cost(imp, conn, qtbot):
    """«30 USD» typed in the amount at the rate of the day 1.7 = 51.00, by value 170 : 85
    -> A 34.00 (204.00, 20.40 a piece), B 17.00 (102.00)."""
    m = imp
    m.ledger.set_rate(m.company_id, "USD", "2026-04-01", 1_700_000)
    doc = usd_receipt(
        m,
        [
            ReceiptLine(m.item_a, m.main, "10", None, currency_amount="100"),
            ReceiptLine(m.item_b, m.main, "5", None, currency_amount="50"),
        ],
    )
    session = Session(
        conn, m.ledger, m.company_id, "Импорт", Catalog(conn, m.company_id), date(2026, 4, 3)
    )
    page = LandedCostPage(session)
    qtbot.addWidget(page)
    lines = m.inventory.load_document(m.company_id, doc).lines
    receipts = {r.id: r for r in receipt_line_choices(conn, m.company_id)}
    page.targets.add([receipts[line.id] for line in lines])
    charges = page.charges
    charges.setData(charges.index(0, charges.columns.index(lc.ACCOUNT)), m.foreign)
    charges.setData(charges.index(0, charges.columns.index(lc.SC1)), m.supplier)
    amount = charges.index(0, charges.columns.index(lc.AMOUNT))
    charges.setData(amount, charges.parse(0, lc.AMOUNT, "30 USD"))
    assert charges.rows[0].amount == 5_100
    assert not page.charges_table.isColumnHidden(charges.columns.index(lc.RATE))
    assert charges.index(0, charges.columns.index(lc.CURRENCY_AMOUNT)).data() == "30.00 USD"
    assert [t.share for t in page.targets.rows] == [3_400, 1_700]
    assert page.save(post=True), page.error.text()
    assert page.doc is not None and page.doc.charges[0].currency_amount == 3_000

    dialog = lc.BatchCostDialog(session, page.doc.id, "Партия")
    qtbot.addWidget(dialog)
    first, _, total = dialog.model.rows
    assert (first.price, first.rate, first.total, first.unit_cost) == (
        "10.00 USD",
        "1.7000",
        20_400,
        2_040,
    )
    assert total.total == 30_600
    copied = dialog.text().splitlines()
    assert copied[1].split("\t")[-2:] == ["204.00", "20.40"]
