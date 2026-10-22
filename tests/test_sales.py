"""«Продажа / Satış»: goods at the average cost and services, revenue, VAT, e-qaimə.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date

import pytest
from PySide6.QtCore import QPersistentModelIndex, Qt

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    STANDARD_VAT_RATE,
    Inventory,
    ReceiptLine,
    SaleLine,
)
from modern_gl.application.ledger import Ledger
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ITEM,
    MEMO,
    QUANTITY,
    SC1,
    SC2,
    VAT,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.inventory_page import InventorySettingsDialog
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import money
from modern_gl.domain.accounts import COST_OF_SALES, OUTPUT_VAT, SALES_REVENUE, SALES_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure import chart_csv
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from modern_gl.reporting.inventory import stock_balances
from modern_gl.reporting.invoices import invoice_report


@dataclass
class Shop:
    ledger: Ledger
    inventory: Inventory
    company_id: int
    acc: dict[str, int]
    item: int
    main: int
    supplier: list[int]
    customer: int
    contract: int

    def receipt(self, day: str, quantity: str, amount: str) -> int:
        return self.inventory.post_receipt(
            self.company_id,
            day,
            [ReceiptLine(self.item, self.main, quantity, amount)],
            self.acc["60"],
            self.supplier,
        )

    def sale(self, day: str, lines: list[SaleLine], **kwargs) -> int:
        return self.inventory.post_sale(
            self.company_id,
            day,
            lines,
            self.acc["62"],
            [self.customer, self.contract],
            "Продажа",
            vat_rate=STANDARD_VAT_RATE,
            **kwargs,
        )

    def postings(self, inv_doc: int) -> list[tuple]:
        """(Dt code, Kt code, amount, memo, invoice) of a warehouse document's GL document."""
        gl = self.inventory.load_document(self.company_id, inv_doc).gl_document_id
        code = {v: k for k, v in self.acc.items()}
        return [
            (
                code[p["debit_account_id"]],
                code[p["credit_account_id"]],
                p["amount"],
                p["memo"],
                p["invoice"],
            )
            for p in self.ledger.conn.execute(
                "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl,)
            )
        ]


def make_shop(conn: sqlite3.Connection, template: str) -> Shop:
    ledger = Ledger(conn, actor="test")
    company_id = ledger.create_company(template)
    apply_chart_template(ledger, company_id, template, "ru")
    acc = {
        row["code"]: row["id"]
        for row in conn.execute(
            "SELECT code, id FROM accounts WHERE company_id = ? AND code IS NOT NULL",
            (company_id,),
        )
    }
    if template == "1c77":  # the codes the tests use, as in the classic chart
        acc |= {"60": acc["60.1"], "62": acc["62.1"]}
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(company_id, "əd", "Ədəd", precision=0)
    inventory_account = acc["41.1"] if template == "1c77" else acc["41"]
    item = inventory.add_item(company_id, "Printer", unit, inventory_account)
    main = inventory.add_warehouse(company_id, "Əsas anbar")
    counterparty = ledger.subconto_kind_id(company_id, "counterparty")
    contract_kind = ledger.subconto_kind_id(company_id, "contract")
    supplier = ledger.add_subconto_value(company_id, counterparty, "Təchizatçı")
    supply = ledger.add_subconto_value(company_id, contract_kind, "Tədarük", owner_id=supplier)
    customer = ledger.add_subconto_value(company_id, counterparty, "Alfa")
    contract = ledger.add_subconto_value(company_id, contract_kind, "Müqavilə 1", owner_id=customer)
    return Shop(
        ledger, inventory, company_id, acc, item, main, [supplier, supply], customer, contract
    )


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def two_lines(shop: Shop) -> list[SaleLine]:
    return [
        SaleLine(shop.item, shop.main, "3", "60", "10.80"),
        SaleLine(None, None, None, "25", "4.50", "Çatdırılma"),
    ]


def test_sale_of_goods_and_a_service_in_the_classic_chart(shop, conn):
    """Received 10 printers for 120.00 (12.00 each). Sold 3 for 60.00 + VAT 10.80 and a
    delivery for 25.00 + VAT 4.50, e-qaimə MT2601001. Classic chart, as its template
    «Реализация с НДС» does: Dt 62 / Kt 46 with VAT, Dt 46 / Kt 68.2 the VAT:
      62 / 46   70.80  Printer      (60.00 + 10.80)
      62 / 46   29.50  Çatdırılma   (25.00 + 4.50)
      46 / 68.2 15.30  НДС          (10.80 + 4.50)
      46 / 41   36.00  Printer      (3 × 12.00)
    The customer owes 100.30; 46 nets 49.00 = 85.00 revenue - 36.00 cost; 7 printers
    worth 84.00 stay."""
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", two_lines(shop), invoice="mt 2601001")

    assert shop.postings(sale) == [
        ("62", "46", 7_080, "Printer", "MT2601001"),
        ("62", "46", 2_950, "Çatdırılma", "MT2601001"),
        ("46", "68.2", 1_530, "НДС", "MT2601001"),
        ("46", "41", 3_600, "Printer", None),
    ]
    customer = conn.execute(
        "SELECT dt_sc1, dt_sc2 FROM postings WHERE debit_account_id = ? LIMIT 1",
        (shop.acc["62"],),
    ).fetchone()
    assert tuple(customer) == (shop.customer, shop.contract)
    balance = stock_balances(conn, shop.company_id)[0]
    assert (balance.quantity, balance.amount) == (7 * QUANTITY_FACTOR, 8_400)

    doc = shop.inventory.load_document(shop.company_id, sale)
    assert doc.doc_type == "sale" and doc.status == "posted"
    assert doc.invoice == "MT2601001" and doc.vat_rate == STANDARD_VAT_RATE
    goods, service = doc.lines
    assert (goods.amount, goods.vat_amount, goods.expense_amount) == (6_000, 1_080, 3_600)
    assert goods.cost_account_id == shop.acc["46"]
    assert (service.item_id, service.warehouse_id, service.quantity) == (None, None, 0)
    assert (service.amount, service.vat_amount, service.memo) == (2_500, 450, "Çatdırılma")

    (row,) = invoice_report(conn, shop.company_id, "2026-01-01", "2026-01-31")
    assert (row.invoice, row.debit, row.credit, row.vat) == ("MT2601001", 10_030, 0, 1_530)
    assert row.counterparty_id == shop.customer and row.contract_id == shop.contract


def test_sale_in_the_1c77_chart_uses_its_sales_accounts(conn):
    """The same sale in the 1C 7.7 chart: 62.1 / 90.1 with VAT, 90.3 / 68.2, 90.2 / 41.1."""
    shop = make_shop(conn, "1c77")
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", two_lines(shop))
    assert [p[:3] for p in shop.postings(sale)] == [
        ("62.1", "90.1", 7_080),
        ("62.1", "90.1", 2_950),
        ("90.3", "68.2", 1_530),
        ("90.2", "41.1", 3_600),
    ]


def test_without_a_vat_charge_account_the_customer_is_charged_the_vat(shop):
    """No account for «НДС начисляется со счёта»: revenue without VAT, the VAT straight
    from the customer: 62 / 46 60.00 and 25.00, 62 [Alfa, Müqavilə 1] / 68.2 15.30."""
    shop.ledger.set_account_role(shop.company_id, SALES_VAT, None)
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", two_lines(shop))
    assert [p[:3] for p in shop.postings(sale)] == [
        ("62", "46", 6_000),
        ("62", "46", 2_500),
        ("62", "68.2", 1_530),
        ("46", "41", 3_600),
    ]


def test_a_service_sale_needs_no_warehouse_and_no_vat(shop):
    """A service without VAT: one posting 62 / 46 500.00, nothing else."""
    sale = shop.inventory.post_sale(
        shop.company_id,
        "2026-02-01",
        [SaleLine(None, None, "1", "500", memo="Mühasibat xidməti, yanvar")],
        shop.acc["62"],
        [shop.customer, shop.contract],
    )
    assert shop.postings(sale) == [("62", "46", 50_000, "Mühasibat xidməti, yanvar", None)]


def test_backdated_receipt_recalculates_the_cost_of_a_sale(shop):
    """Sold 3 of 10 bought for 120.00: cost 36.00. A receipt of 10 more for 180.00 dated
    before the sale makes the average (120 + 180) / 20 = 15.00: the cost becomes 45.00.
    The revenue and the GL document's number stay."""
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", two_lines(shop))
    gl_number = shop.ledger.conn.execute(
        "SELECT number FROM documents WHERE id = ?",
        (shop.inventory.load_document(shop.company_id, sale).gl_document_id,),
    ).fetchone()[0]

    shop.receipt("2026-01-15", "10", "180")

    postings = shop.postings(sale)
    assert postings[-1][:3] == ("46", "41", 4_500)
    assert [p[2] for p in postings[:3]] == [7_080, 2_950, 1_530]
    assert (
        shop.ledger.conn.execute(
            "SELECT number FROM documents WHERE id = ?",
            (shop.inventory.load_document(shop.company_id, sale).gl_document_id,),
        ).fetchone()[0]
        == gl_number
    )


def test_sale_cannot_take_more_than_there_is(shop, conn):
    shop.receipt("2026-01-10", "2", "24")
    with pytest.raises(ValidationError, match="недостаточно товара «Printer»"):
        shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "3", "60")])
    sales = "SELECT COUNT(*) FROM inventory_documents WHERE doc_type = 'sale'"
    assert conn.execute(sales).fetchone()[0] == 0
    balance = stock_balances(conn, shop.company_id)[0]
    assert balance.quantity == 2 * QUANTITY_FACTOR


def test_unfinished_sale_draft_and_the_missing_fields(shop):
    """A draft may lack the warehouse, quantity and amount; posting names what is missing."""
    shop.receipt("2026-01-10", "10", "120")
    draft = shop.inventory.create_sale_draft(
        shop.company_id,
        "2026-01-20",
        [SaleLine(shop.item, None, None, None)],
        shop.acc["62"],
        [shop.customer],
    )
    with pytest.raises(ValidationError, match="строка 1: не указан склад"):
        shop.inventory.post_document(shop.company_id, draft)
    shop.inventory.update_sale_draft(
        shop.company_id,
        draft,
        "2026-01-20",
        [SaleLine(shop.item, shop.main, "1", None), SaleLine(None, None, None, "10")],
        shop.acc["62"],
        [shop.customer],
    )
    with pytest.raises(ValidationError, match="строка 1: не указана сумма"):
        shop.inventory.post_document(shop.company_id, draft)
    shop.inventory.update_sale_draft(
        shop.company_id,
        draft,
        "2026-01-20",
        [SaleLine(shop.item, shop.main, "1", "20"), SaleLine(None, None, None, "10")],
        shop.acc["62"],
        [shop.customer],
    )
    with pytest.raises(ValidationError, match="строка 2: укажите товар или что за услуга"):
        shop.inventory.post_document(shop.company_id, draft)
    with pytest.raises(ValidationError, match="у услуги нет склада"):
        shop.inventory.update_sale_draft(
            shop.company_id,
            draft,
            "2026-01-20",
            [SaleLine(None, shop.main, None, "10", memo="Xidmət")],
            shop.acc["62"],
        )


def test_sale_needs_the_revenue_account(shop):
    shop.ledger.set_account_role(shop.company_id, SALES_REVENUE, None)
    shop.ledger.conn.execute(  # no account of the «sales» type to fall back on either
        "UPDATE accounts SET account_type = NULL WHERE company_id = ? AND code = '46'",
        (shop.company_id,),
    )
    with pytest.raises(ValidationError, match="не указан счёт «Выручка»"):
        shop.sale("2026-01-20", [SaleLine(None, None, None, "10", memo="Xidmət")])


def test_posted_sale_is_edited_in_place_and_unposted(shop, conn):
    """Edited in place: 2 printers instead of 3 -> cost 24.00, revenue 40.00 + VAT 7.20.
    Unposted: the stock is back to 10 and the GL document is gone."""
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "3", "60", "10.80")])
    line_id = shop.inventory.load_document(shop.company_id, sale).lines[0].id
    with shop.inventory.reposting(shop.company_id, sale):
        shop.inventory.update_sale_draft(
            shop.company_id,
            sale,
            "2026-01-20",
            [SaleLine(shop.item, shop.main, "2", "40", "7.20", line_id=line_id)],
            shop.acc["62"],
            [shop.customer, shop.contract],
            vat_rate=STANDARD_VAT_RATE,
        )
    assert [p[:3] for p in shop.postings(sale)] == [
        ("62", "46", 4_720),
        ("46", "68.2", 720),
        ("46", "41", 2_400),
    ]
    assert stock_balances(conn, shop.company_id)[0].quantity == 8 * QUANTITY_FACTOR

    shop.inventory.unpost_document(shop.company_id, sale)
    doc = shop.inventory.load_document(shop.company_id, sale)
    assert (doc.status, doc.gl_document_id) == ("draft", None)
    assert doc.lines[0].expense_amount == 0 and doc.lines[0].amount == 4_000
    assert stock_balances(conn, shop.company_id)[0].quantity == 10 * QUANTITY_FACTOR
    shop.inventory.delete_document(shop.company_id, sale)


def test_late_landed_cost_of_sold_goods_goes_to_the_cost_of_sales(shop, conn):
    """10 printers for 100.00, 4 sold (cost 40.00), then delivery 20.00 on the batch:
    6 / 10 of it, 12.00, to the stock; 4 / 10, 8.00, to the cost of sales (46)."""
    receipt = shop.receipt("2026-01-10", "10", "100")
    receipt_line = shop.inventory.load_document(shop.company_id, receipt).lines[0].id
    shop.sale("2026-01-12", [SaleLine(shop.item, shop.main, "4", "80")])
    landed = shop.inventory.post_landed_cost(
        shop.company_id, "2026-01-15", [receipt_line], "20", shop.acc["60"], shop.supplier
    )
    assert [p[:3] for p in shop.postings(landed)] == [("41", "60", 1_200), ("46", "60", 800)]
    balance = stock_balances(conn, shop.company_id)[0]
    assert (balance.quantity, balance.amount) == (6 * QUANTITY_FACTOR, 7_200)


@pytest.mark.parametrize(
    ("template", "codes"),
    [
        ("classic", ("46", "46", "46", "68.2")),
        ("1c77", ("90.1", "90.2", "90.3", "68.2")),
    ],
)
def test_chart_templates_set_the_sale_accounts(ledger, template, codes):
    company_id = ledger.create_company(template)
    apply_chart_template(ledger, company_id, template, "ru")
    for role, code in zip(
        (SALES_REVENUE, COST_OF_SALES, SALES_VAT, OUTPUT_VAT), codes, strict=True
    ):
        assert ledger.account_role(company_id, role) == ledger.account_id(company_id, code)


def test_migration_keeps_inventory_and_sets_the_sale_accounts(tmp_path, monkeypatch):
    """A file of version 21 with a classic chart and a receipt draft (written as the old
    program did): after 0022-0023 the draft and its line keep their ids, the sale accounts
    are set, a sale posts, and posted documents are protected as before."""
    path = tmp_path / "v21.gl"
    old = sqlite3.connect(path, isolation_level=None)
    old.row_factory = sqlite3.Row
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 21:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.execute("PRAGMA foreign_keys = ON")
    # today's chart template without 76H, whose account type came later (D65, 0031), and
    # without optional subconto ("employee?", D78), whose column came later too (0028)
    templates = tmp_path / "templates"
    shutil.copytree(chart_csv.TEMPLATES_DIR, templates)
    for csv in templates.glob("chart_classic_*.csv"):
        lines = csv.read_text(encoding="utf-8").replace("?;", ";").splitlines(keepends=True)
        csv.write_text("".join(x for x in lines if not x.startswith("76H;")), encoding="utf-8")
    monkeypatch.setattr(chart_csv, "TEMPLATES_DIR", templates)
    shop = make_shop(old, "classic")
    old.execute("DELETE FROM account_roles WHERE role NOT IN ('input_vat', 'fx_transit')")
    old.execute(
        "INSERT INTO inventory_documents (id, company_id, number, doc_date, doc_type, status, "
        "created_at) VALUES (7, ?, 1, '2026-01-10', 'receipt', 'draft', '2026-01-10')",
        (shop.company_id,),
    )
    old.execute(
        "INSERT INTO inventory_lines (id, company_id, document_id, line_no, item_id, "
        "warehouse_id, quantity, amount, inventory_amount, offset_account_id, offset_sc1, "
        "offset_sc2) VALUES (70, ?, 7, 1, ?, ?, 10000000, 12000, 12000, ?, ?, ?)",
        (shop.company_id, shop.item, shop.main, shop.acc["60"], *shop.supplier),
    )
    old.execute("UPDATE companies SET last_inventory_number = 1")
    old.close()

    conn = connect(path)
    try:
        shop.ledger, shop.inventory = Ledger(conn), Inventory(conn)
        roles = dict(conn.execute("SELECT role, account_id FROM account_roles").fetchall())
        assert roles[SALES_REVENUE] == roles[COST_OF_SALES] == roles[SALES_VAT] == shop.acc["46"]
        assert roles[OUTPUT_VAT] == shop.acc["68.2"]
        shop.inventory.post_document(shop.company_id, 7)
        doc = shop.inventory.load_document(shop.company_id, 7)
        assert (doc.status, doc.lines[0].id, doc.lines[0].amount) == ("posted", 70, 12_000)
        sale = shop.sale("2026-01-20", two_lines(shop))
        assert shop.postings(sale)[-1][:3] == ("46", "41", 3_600)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE inventory_lines SET amount = 1 WHERE id = 70")
    finally:
        conn.close()


def sale_page(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    session = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        working_date=date(2026, 1, 20),
    )
    page = InventoryDocumentPage(session, doc_type="sale")
    qtbot.addWidget(page)
    return page


def test_sale_page_posts_goods_and_a_service(shop, conn, qtbot):
    """The page of a new sale: VAT 18% (the company has an output VAT account), the
    customer's account 62 prefilled, a service line without a warehouse. Posted, it gives
    the postings of the classic-chart test above."""
    shop.receipt("2026-01-10", "10", "120")
    page = sale_page(shop, conn, qtbot)
    model = page.model
    assert page.title() == "Новое: Продажа"
    assert page._chosen_vat_rate() == STANDARD_VAT_RATE
    assert not page.invoice.isHidden() and page.basis.isHidden()
    assert model.headerData(model.columns.index(ITEM), Qt.Orientation.Horizontal) == (
        "Товар / услуга"
    )
    assert model.rows[0].offset_account_id == shop.acc["62"]

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    put(0, ITEM, shop.item)
    put(0, WAREHOUSE, shop.main)
    put(0, QUANTITY, 3 * QUANTITY_FACTOR)
    put(0, AMOUNT, 6_000)
    assert model.rows[0].vat_amount == 1_080  # 60.00 * 18%
    put(0, SC1, shop.customer)
    put(0, SC2, shop.contract)
    model.insert_row()
    put(1, MEMO, "Çatdırılma")
    put(1, AMOUNT, 2_500)
    put(1, SC1, shop.customer)
    put(1, SC2, shop.contract)
    assert model.rows[1].vat_amount == 450
    assert not model.flags(model.index(1, model.columns.index(WAREHOUSE)))  # a service
    assert model.data(model.index(1, model.columns.index(ITEM))) == "Çatdırılma"
    assert (page.vat_total.text(), page.total.text()) == (money(1_530), money(10_030))
    page.invoice.setText("MT2601001")

    assert page.save(post=True), page.error.text()
    assert page.doc is not None and page.doc.status == "posted"
    assert page.title() == f"Продажа №{page.doc.number}"
    assert [p[:3] for p in shop.postings(page.doc.id)] == [
        ("62", "46", 7_080),
        ("62", "46", 2_950),
        ("46", "68.2", 1_530),
        ("46", "41", 3_600),
    ]
    assert page.invoice.text() == "MT2601001"
    assert [row.item_id for row in page.model.rows] == [shop.item, None]
    shown = [page.model.columns[c] for c in range(page.model.columnCount()) if page._shown(c)]
    assert AMOUNT in shown  # not hidden by the columns of the model before


def test_sale_page_names_a_service_line_without_a_memo(shop, conn, qtbot):
    page = sale_page(shop, conn, qtbot)
    model = page.model
    model.setData(model.index(0, model.columns.index(AMOUNT)), 2_500)
    model.setData(model.index(0, model.columns.index(SC1)), shop.customer)
    model.setData(model.index(0, model.columns.index(SC2)), shop.contract)
    assert not page.save(post=True)
    assert page.error.text() == "строка 1: укажите товар или что за услуга"


def test_settings_choose_the_sale_accounts(shop, conn, qtbot):
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    dialog = InventorySettingsDialog(session)
    qtbot.addWidget(dialog)
    vat_from = dialog.sale_roles[SALES_VAT]
    assert vat_from.currentData() == shop.acc["46"]
    vat_from.setCurrentIndex(0)  # «— счёт покупателя —»
    revenue = dialog.sale_roles[SALES_REVENUE]
    revenue.setCurrentIndex(revenue.findData(shop.acc["47"]))
    dialog._save()
    assert shop.ledger.account_role(shop.company_id, SALES_VAT) is None
    assert shop.ledger.account_role(shop.company_id, SALES_REVENUE) == shop.acc["47"]


def test_opened_sale_shows_its_amount_column(shop, conn, qtbot):
    """A page opened by id starts as a receipt; the columns hidden for the receipt's model
    (the currency amount) must not hide the sale's amount at the same position."""
    sale = shop.sale("2026-01-20", [SaleLine(None, None, None, "25", memo="Çatdırılma")])
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, document_id=sale)
    qtbot.addWidget(page)
    shown = [page.model.columns[c] for c in range(page.model.columnCount()) if page._shown(c)]
    assert AMOUNT in shown and VAT in shown


def test_a_name_that_is_no_item_becomes_a_service(shop, conn, qtbot, monkeypatch):
    """Typed in «Товар / услуга», a name the items do not have is asked about; «Услуга»
    makes it the service line's text."""
    page = sale_page(shop, conn, qtbot)
    monkeypatch.setattr(page, "_service_or_item", lambda text: "service")
    index = page.model.index(0, page.model.columns.index(ITEM))
    page._create_item(QPersistentModelIndex(index), "Mühasibat xidməti")
    row = page.model.rows[0]
    assert (row.item_id, row.memo) == (None, "Mühasibat xidməti")
    assert page.model.data(index) == "Mühasibat xidməti"
    monkeypatch.setattr(page, "_service_or_item", lambda text: None)  # cancelled
    page._create_item(QPersistentModelIndex(index), "Başqa")
    assert page.model.rows[0].memo == "Mühasibat xidməti"
