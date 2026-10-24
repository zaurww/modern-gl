"""«Расходы по партии» (D33): several receipts, several charges, allocation, editing."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCompleter

from modern_gl.application import queries
from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import (
    Inventory,
    LandedCostCharge,
    LandedCostTarget,
    ReceiptLine,
    split_charges,
)
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.desktop.landed_cost_page import (
    ACCOUNT,
    AMOUNT,
    SC1,
    SHARE,
    UNIT_COST,
    VAT,
    ChargeRow,
    LandedCostPage,
    cost_source_picker,
    source_label,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from modern_gl.reporting.inventory import (
    cost_sources,
    list_inventory_documents,
    receipt_line_choices,
    stock_balances,
)


@dataclass
class Batch:
    inventory: Inventory
    ledger: Ledger
    company_id: int
    item_a: int
    item_b: int
    main: int
    stock: int  # 41
    payable: int  # 60
    expense: int  # 44
    vat: int  # 19
    supplier: int
    broker: int
    line_a: int  # receipt №1: A 10 pcs for 100.00
    line_b: int  # receipt №2: B 30 pcs for 200.00
    broker_doc: int  # GL: Dt 44 / Ct 60 [broker] 90.00


@pytest.fixture
def batch(ledger, conn) -> Batch:
    cid = ledger.create_company("Партия")
    item_kind = ledger.add_subconto_kind(cid, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    counterparty = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    stock = ledger.add_account(
        cid, "41", "Товары", subconto=[item_kind, warehouse_kind], account_class="asset"
    )
    payable = ledger.add_account(
        cid, "60", "Поставщики", subconto=[counterparty], account_class="liability"
    )
    expense = ledger.add_account(cid, "44", "Расходы на продажу", account_class="expense")
    vat = ledger.add_account(cid, "19", "НДС", subconto=[counterparty], account_class="asset")
    ledger.set_account_role(cid, INPUT_VAT, vat)
    supplier = ledger.add_subconto_value(cid, counterparty, "Поставщик")
    broker = ledger.add_subconto_value(cid, counterparty, "Брокер")
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "шт", "Штука")
    item_a = inventory.add_item(cid, "Товар A", unit, stock)
    item_b = inventory.add_item(cid, "Товар B", unit, stock)
    main = inventory.add_warehouse(cid, "Основной")

    def receipt(item: int, quantity: str, amount: str) -> int:
        doc = inventory.post_receipt(
            cid, "2026-03-01", [ReceiptLine(item, main, quantity, amount)], payable, [supplier]
        )
        return inventory.load_document(cid, doc).lines[0].id

    line_a = receipt(item_a, "10", "100")
    line_b = receipt(item_b, "30", "200")
    broker_doc = ledger.post_new(
        cid, "2026-03-02", [PostingInput(expense, payable, Decimal("90"), (), (broker,))]
    )
    return Batch(
        inventory,
        ledger,
        cid,
        item_a,
        item_b,
        main,
        stock,
        payable,
        expense,
        vat,
        supplier,
        broker,
        line_a,
        line_b,
        broker_doc,
    )


def freight(b: Batch, amount="60", vat="10.80") -> LandedCostCharge:
    return LandedCostCharge(amount, b.payable, [b.supplier], vat_amount=vat, memo="Доставка")


def broker_fee(b: Batch, amount="90") -> LandedCostCharge:
    return LandedCostCharge(amount, source_document_id=b.broker_doc, source_line_no=1)


def post_batch(b: Batch, charges, method="value", targets=None) -> int:
    doc = b.inventory.create_landed_cost_draft(
        b.company_id,
        "2026-03-05",
        targets or [LandedCostTarget(b.line_a), LandedCostTarget(b.line_b)],
        charges,
        method,
        "Партия 1",
    )
    b.inventory.post_document(b.company_id, doc)
    return doc


def postings(conn, b: Batch, inv_doc: int) -> list[tuple]:
    gl_id = b.inventory.load_document(b.company_id, inv_doc).gl_document_id
    return [
        (r["debit_account_id"], r["dt_sc1"], r["credit_account_id"], r["ct_sc1"], r["amount"])
        for r in conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl_id,)
        )
    ]


def values(b: Batch, conn) -> dict[int, int]:
    return {row.item_id: row.amount for row in stock_balances(conn, b.company_id)}


def subconto_of(conn, item_id: int) -> int:
    return conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (item_id,)
    ).fetchone()[0]


def test_split_charges_keeps_both_totals():
    # targets 50.00 and 100.00; charges 60.00 then 90.00
    shares = split_charges([(1, 6_000), (2, 9_000)], {10: 5_000, 20: 10_000})
    assert shares == {(1, 10): 2_000, (1, 20): 4_000, (2, 10): 3_000, (2, 20): 6_000}
    odd = split_charges([(1, 1), (2, 2)], {10: 2, 20: 1})
    assert sum(v for (c, _), v in odd.items() if c == 1) == 1
    assert sum(v for (_, t), v in odd.items() if t == 10) == 2


def test_batch_with_typed_charge_and_gl_posting_by_value(batch, conn):
    """Freight 60.00 (+ VAT 10.80) typed in the document and the broker's 90.00 already
    posted to 44. By value 100 : 200 the batch takes 150.00: A 50.00, B 100.00.
    Freight: A 20.00, B 40.00; broker: A 30.00, B 60.00 — moved from 44 to stock."""
    b = batch
    doc = post_batch(b, [freight(b), broker_fee(b)])

    loaded = b.inventory.load_document(b.company_id, doc)
    assert loaded.status == "posted" and loaded.allocation_method == "value"
    assert [line.amount for line in loaded.lines] == [5_000, 10_000]
    assert [line.inventory_amount for line in loaded.lines] == [5_000, 10_000]
    assert values(b, conn) == {b.item_a: 15_000, b.item_b: 30_000}
    a, b_item = subconto_of(conn, b.item_a), subconto_of(conn, b.item_b)
    assert postings(conn, b, doc) == [
        (b.stock, a, b.payable, b.supplier, 2_000),
        (b.stock, a, b.expense, None, 3_000),
        (b.stock, b_item, b.payable, b.supplier, 4_000),
        (b.stock, b_item, b.expense, None, 6_000),
        (b.vat, b.supplier, b.payable, b.supplier, 1_080),
    ]
    balance_44 = conn.execute(
        "SELECT SUM(CASE WHEN debit_account_id = ? THEN amount ELSE -amount END) "
        "FROM postings WHERE ? IN (debit_account_id, credit_account_id)",
        (b.expense, b.expense),
    ).fetchone()[0]
    assert balance_44 == 0  # the broker's invoice is now in the cost of the goods


def test_batch_by_quantity(batch, conn):
    """150.00 by quantity 10 : 30 -> A 37.50, B 112.50."""
    b = batch
    doc = post_batch(b, [freight(b, vat="0"), broker_fee(b)], method="quantity")
    lines = b.inventory.load_document(b.company_id, doc).lines
    assert [line.amount for line in lines] == [3_750, 11_250]
    assert values(b, conn) == {b.item_a: 13_750, b.item_b: 31_250}


def test_manual_allocation_must_add_up(batch, conn):
    b = batch
    targets = [LandedCostTarget(b.line_a, "100"), LandedCostTarget(b.line_b, "40")]
    with pytest.raises(ValidationError, match=r"распределено 140.00, а расходов 150.00"):
        post_batch(b, [freight(b), broker_fee(b)], "manual", targets)
    targets = [LandedCostTarget(b.line_a, "100"), LandedCostTarget(b.line_b, "50")]
    doc = post_batch(b, [freight(b), broker_fee(b)], "manual", targets)
    assert values(b, conn) == {b.item_a: 20_000, b.item_b: 25_000}
    shares = dict(
        ((r["charge_id"], r["line_id"]), r["amount"])
        for r in conn.execute("SELECT * FROM landed_cost_shares WHERE document_id = ?", (doc,))
    )
    assert sum(shares.values()) == 15_000


def test_gl_posting_cannot_be_allocated_twice(batch):
    b = batch
    post_batch(b, [broker_fee(b, "50")])
    assert [(s.document_id, s.left) for s in cost_sources(b.inventory.conn, b.company_id)] == [
        (b.broker_doc, 4_000)
    ]
    with pytest.raises(ValidationError, match=r"осталось 40.00"):
        post_batch(b, [broker_fee(b, "41")])
    post_batch(b, [broker_fee(b, "40")])
    assert cost_sources(b.inventory.conn, b.company_id) == []


def test_picker_and_posting_count_what_is_allocated_alike(batch):
    """The broker's 90.00: a posted batch took 50.00. Another document sees 40.00 left
    and may take no more; the batch itself, when edited, sees all 90.00 free."""
    b = batch
    taken = post_batch(b, [broker_fee(b, "50")])
    conn = b.inventory.conn
    left = {s.document_id: s.left for s in cost_sources(conn, b.company_id, taken)}
    assert left == {b.broker_doc: 9_000}
    draft = b.inventory.create_landed_cost_draft(
        b.company_id, "2026-03-06", [LandedCostTarget(b.line_a)], [broker_fee(b, "41")]
    )
    assert [s.left for s in cost_sources(conn, b.company_id, draft)] == [4_000]
    with pytest.raises(ValidationError, match=r"уже распределено 50.00, осталось 40.00"):
        b.inventory.post_document(b.company_id, draft)
    with b.inventory.reposting(b.company_id, taken):
        b.inventory.update_landed_cost_draft(
            b.company_id,
            taken,
            "2026-03-05",
            [LandedCostTarget(b.line_a)],
            [broker_fee(b, "90")],
            "value",
            "Партия 1",
        )
    assert cost_sources(conn, b.company_id) == []


def test_gl_document_taken_as_charge_is_protected(batch, conn):
    b = batch
    assert queries.document_owner(conn, b.company_id, b.broker_doc, "uses") is None
    doc = post_batch(b, [broker_fee(b)])
    number = b.inventory.load_document(b.company_id, doc).number
    owner = queries.DocumentOwner("landed_cost", doc, number)
    assert queries.document_owner(conn, b.company_id, b.broker_doc, "uses") == owner
    assert queries.document_owner(conn, b.company_id, b.broker_doc) is None  # made by hand
    with pytest.raises(ValidationError, match="расход партии"):
        b.ledger.delete_document(b.company_id, b.broker_doc)
    with pytest.raises(ValidationError, match="расход партии"):
        b.ledger.unpost(b.company_id, b.broker_doc)


def test_charge_from_gl_has_no_vat_of_its_own(batch):
    b = batch
    charge = LandedCostCharge(
        "90", source_document_id=b.broker_doc, source_line_no=1, vat_amount="16.20"
    )
    with pytest.raises(ValidationError, match="НДС уже учтён"):
        post_batch(b, [charge])


def test_warehouse_postings_are_not_charges(batch):
    b = batch
    receipt_gl = b.inventory.load_document(
        b.company_id,
        b.inventory.conn.execute(
            "SELECT document_id FROM inventory_lines WHERE id = ?", (b.line_a,)
        ).fetchone()[0],
    ).gl_document_id
    assert receipt_gl is not None
    charge = LandedCostCharge("10", source_document_id=receipt_gl, source_line_no=1)
    with pytest.raises(ValidationError, match="складского документа"):
        post_batch(b, [charge])


def test_posted_batch_is_edited_in_place(batch, conn):
    b = batch
    doc = post_batch(b, [freight(b, vat="0"), broker_fee(b)])
    before = b.inventory.load_document(b.company_id, doc)
    with b.inventory.reposting(b.company_id, doc):
        b.inventory.update_landed_cost_draft(
            b.company_id,
            doc,
            "2026-03-05",
            [LandedCostTarget(b.line_a, line_id=before.lines[0].id)],  # only A now
            [freight(b, "30", "0")],
            "value",
            "Партия 1",
        )
    after = b.inventory.load_document(b.company_id, doc)
    assert after.status == "posted" and after.gl_document_id == before.gl_document_id
    assert [line.amount for line in after.lines] == [3_000]
    assert values(b, conn) == {b.item_a: 13_000, b.item_b: 20_000}
    # the broker's posting is free again
    assert [s.left for s in cost_sources(conn, b.company_id)] == [9_000]

    b.inventory.unpost_document(b.company_id, doc)
    assert values(b, conn) == {b.item_a: 10_000, b.item_b: 20_000}


def test_landed_cost_follows_an_edited_receipt(batch, conn):
    """The receipt of A becomes 400.00: by value 400 : 200 the batch's 150.00 is now
    A 100.00, B 50.00."""
    b = batch
    doc = post_batch(b, [freight(b, vat="0"), broker_fee(b)])
    receipt_doc = conn.execute(
        "SELECT document_id FROM inventory_lines WHERE id = ?", (b.line_a,)
    ).fetchone()[0]
    with b.inventory.reposting(b.company_id, receipt_doc):
        b.inventory.update_receipt_draft(
            b.company_id,
            receipt_doc,
            "2026-03-01",
            [ReceiptLine(b.item_a, b.main, "10", "400", line_id=b.line_a)],
            b.payable,
            [b.supplier],
        )
    lines = b.inventory.load_document(b.company_id, doc).lines
    assert [line.amount for line in lines] == [10_000, 5_000]


def test_unfinished_batch_names_the_missing_field(batch):
    b = batch
    doc = b.inventory.create_landed_cost_draft(
        b.company_id, "2026-03-05", [LandedCostTarget(b.line_a)], [LandedCostCharge(None)]
    )
    with pytest.raises(LedgerError, match="расход 1: не указана сумма"):
        b.inventory.post_document(b.company_id, doc)
    b.inventory.update_landed_cost_draft(
        b.company_id, doc, "2026-03-05", [LandedCostTarget(b.line_a)], [LandedCostCharge("5")]
    )
    with pytest.raises(LedgerError, match="расход 1: не указан счёт"):
        b.inventory.post_document(b.company_id, doc)


def test_migration_turns_old_landed_cost_into_one_charge(tmp_path):
    path = tmp_path / "v10.gl"
    old = sqlite3.connect(path, isolation_level=None)
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 10:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.executescript(
        """
        INSERT INTO companies (id, name, created_at) VALUES (1, 'A', '2026-01-01');
        INSERT INTO subconto_kinds (id, company_id, code, name) VALUES (1, 1, 'item', 'T');
        INSERT INTO subconto_values (id, company_id, kind_id, name) VALUES (1, 1, 1, 'X');
        INSERT INTO subconto_values (id, company_id, kind_id, name) VALUES (2, 1, 1, 'W');
        INSERT INTO accounts (id, company_id, code, name) VALUES (1, 1, '41', 'Товары');
        INSERT INTO accounts (id, company_id, code, name) VALUES (2, 1, '60', 'Поставщики');
        INSERT INTO inventory_units (id, company_id, code, name) VALUES (1, 1, 'шт', 'шт');
        INSERT INTO inventory_items (id, company_id, subconto_value_id, unit_id,
            inventory_account_id) VALUES (1, 1, 1, 1, 1);
        INSERT INTO warehouses (id, company_id, subconto_value_id) VALUES (1, 1, 2);
        INSERT INTO inventory_documents (id, company_id, number, doc_date, doc_type, status,
            created_at) VALUES (1, 1, 1, '2026-01-01', 'receipt', 'draft', 'x');
        INSERT INTO inventory_lines (id, company_id, document_id, line_no, item_id,
            warehouse_id, quantity, amount) VALUES (1, 1, 1, 1, 1, 1, 1000000, 10000);
        UPDATE inventory_documents SET status = 'posted' WHERE id = 1;
        INSERT INTO inventory_documents (id, company_id, number, doc_date, doc_type, status,
            created_at) VALUES (2, 1, 2, '2026-01-02', 'landed_cost', 'draft', 'x');
        INSERT INTO inventory_lines (id, company_id, document_id, line_no, item_id,
            warehouse_id, amount, offset_account_id, source_receipt_line_id)
            VALUES (2, 1, 2, 1, 1, 1, 500, 2, 1);
        UPDATE inventory_documents SET status = 'posted' WHERE id = 2;
        """
    )
    old.close()

    upgraded = connect(path)
    try:
        charge = upgraded.execute("SELECT * FROM landed_cost_charges").fetchone()
        assert (charge["document_id"], charge["account_id"], charge["amount"]) == (2, 2, 500)
        share = upgraded.execute("SELECT * FROM landed_cost_shares").fetchone()
        assert (share["charge_id"], share["line_id"], share["amount"]) == (charge["id"], 2, 500)
        method = upgraded.execute(
            "SELECT allocation_method FROM inventory_documents WHERE id = 2"
        ).fetchone()[0]
        assert method == "manual"
    finally:
        upgraded.close()


# ---- the page ------------------------------------------------------------------------


def lc_page(b: Batch, conn, qtbot, document_id: int | None = None) -> LandedCostPage:
    session = Session(
        conn,
        b.ledger,
        b.company_id,
        "Партия",
        Catalog(conn, b.company_id),
        working_date=date(2026, 3, 5),
    )
    page = LandedCostPage(session, document_id)
    qtbot.addWidget(page)
    return page


def test_charge_account_cell_holds_on_a_group(batch, conn, qtbot):
    b = batch
    b.ledger.add_account(b.company_id, "76", "Прочие расчёты", is_group=True)
    for code, name in (("76.1", "С подотчётными"), ("76.2", "С прочими")):
        b.ledger.add_account(b.company_id, code, name, parent="76", account_class="liability")
    page = lc_page(b, conn, qtbot)
    page.show()
    table, charges = page.charges_table, page.charges
    index = charges.index(0, charges.columns.index(ACCOUNT))
    table.setCurrentIndex(index)
    table.edit(index)
    editor = table.indexWidget(index)
    editor.setText("76")
    editor.textEdited.emit(editor.text())
    popup = editor.findChild(QCompleter).popup()
    assert popup.model().rowCount() == 2 and not popup.currentIndex().isValid()

    qtbot.keyClick(editor, Qt.Key.Key_Return)  # a group: stays in the cell
    QApplication.processEvents()
    assert charges.rows[0].account_id == b.payable
    assert table.indexWidget(index) is editor
    qtbot.keyClick(popup, Qt.Key.Key_Return)  # the first subaccount, now highlighted
    assert charges.rows[0].account_id == page.s.catalog.by_code["76.1"].id


def test_landed_cost_page_previews_and_posts(batch, conn, qtbot):
    b = batch
    page = lc_page(b, conn, qtbot)
    receipts = {r.id: r for r in receipt_line_choices(conn, b.company_id)}
    page.targets.add([receipts[b.line_a], receipts[b.line_b]])
    charges = page.charges
    assert charges.rows[0].account_id == b.payable  # a new charge starts on 60
    charges.setData(charges.index(0, charges.columns.index(SC1)), b.supplier)
    charges.setData(charges.index(0, charges.columns.index(AMOUNT)), 6_000)
    vat = charges.parse(0, VAT, "18%")  # 60.00 * 18% = 10.80
    charges.setData(charges.index(0, charges.columns.index(VAT)), vat)
    source = cost_sources(conn, b.company_id)[0]
    charges.insert_row(
        ChargeRow(
            account_id=source.debit_account_id,
            amount=source.left,
            source=(source.document_id, source.line_no),
            source_label=source_label(source),
        )
    )
    # by value 100 : 200 the 150.00 previews as A 50.00 (15.00 a piece), B 100.00
    assert [t.share for t in page.targets.rows] == [5_000, 10_000]
    unit_cost = page.targets.index(0, page.targets.columns.index(UNIT_COST))
    assert unit_cost.data() == "15.00"
    assert page.totals["total"].text() == "150.00"
    assert page.totals["vat"].text() == "10.80"
    assert not charges.editable(1, ACCOUNT)  # the GL posting's account is not changed

    assert page.save(post=True), page.error.text()
    assert page.doc is not None and page.doc.status == "posted"
    assert values(b, conn) == {b.item_a: 15_000, b.item_b: 30_000}

    again = lc_page(b, conn, qtbot, page.doc.id)
    assert [c.amount for c in again.charges.rows] == [6_000, 9_000]
    assert again.charges.rows[1].source_label.startswith("№")
    assert [t.share for t in again.targets.rows] == [5_000, 10_000]


def test_landed_cost_page_manual_allocation(batch, conn, qtbot):
    b = batch
    page = lc_page(b, conn, qtbot)
    receipts = {r.id: r for r in receipt_line_choices(conn, b.company_id)}
    page.targets.add([receipts[b.line_a], receipts[b.line_b]])
    charges = page.charges
    charges.setData(charges.index(0, charges.columns.index(SC1)), b.supplier)
    charges.setData(charges.index(0, charges.columns.index(AMOUNT)), 3_000)
    page.method.setCurrentIndex(page.method.findData("manual"))
    page._changed()
    targets = page.targets
    share = targets.columns.index(SHARE)
    assert targets.editable(0, SHARE)
    targets.setData(targets.index(0, share), 1_000)
    assert not page.save(post=True)
    assert "распределено 10.00" in page.error.text()
    targets.setData(targets.index(1, share), 2_000)
    assert page.save(post=True), page.error.text()
    assert values(b, conn) == {b.item_a: 11_000, b.item_b: 22_000}


def test_cost_source_picker_shows_expenses_until_all_are_asked(batch, conn, qtbot):
    b = batch
    b.ledger.post_new(
        b.company_id,
        "2026-03-03",
        [PostingInput(b.vat, b.payable, Decimal("5"), (b.broker,), (b.broker,))],
    )
    page = lc_page(b, conn, qtbot)
    picker = cost_source_picker(page.s, None, page)
    qtbot.addWidget(picker)
    assert [row.document_id for row in picker.model.rows] == [b.broker_doc]  # 44 only
    picker.show_all.setChecked(True)
    assert len(picker.model.rows) == 2


def test_draft_batches_do_not_hide_what_is_left_of_a_posting(batch, conn):
    """As when posting, only posted batches count: a draft may still change."""
    b = batch
    b.inventory.create_landed_cost_draft(
        b.company_id, "2026-03-05", [LandedCostTarget(b.line_a)], [broker_fee(b)]
    )
    assert [s.left for s in cost_sources(conn, b.company_id)] == [9_000]


def test_document_list_names_the_cost_types_of_a_batch(batch, conn):
    b = batch
    freight_type = b.inventory.add_landed_cost_type(b.company_id, "Доставка")
    customs_type = b.inventory.add_landed_cost_type(b.company_id, "Таможня")
    post_batch(
        b,
        [
            LandedCostCharge("10", b.payable, [b.supplier], cost_type_id=freight_type),
            LandedCostCharge("5", b.payable, [b.supplier], cost_type_id=customs_type),
        ],
    )
    batch_row = next(
        d for d in list_inventory_documents(conn, b.company_id) if d.doc_type == "landed_cost"
    )
    assert batch_row.cost_type_name == "Доставка, Таможня"
    assert batch_row.amount == 1_500


def test_input_vat_account_comes_from_the_account_type(batch):
    """Without a chosen account the only account of type «input VAT» is used."""
    b = batch
    b.ledger.set_account_role(b.company_id, INPUT_VAT, None)
    assert b.ledger.account_role(b.company_id, INPUT_VAT) is None  # 19 has no type yet
    b.ledger.set_account_type(b.company_id, b.vat, "input_vat")
    assert b.ledger.account_role(b.company_id, INPUT_VAT) == b.vat
    other = b.ledger.add_account(b.company_id, "19.9", "НДС прочий", account_type="input_vat")
    assert b.ledger.account_role(b.company_id, INPUT_VAT) is None  # two: choose one
    b.ledger.set_account_role(b.company_id, INPUT_VAT, other)
    assert b.ledger.account_role(b.company_id, INPUT_VAT) == other


def test_gl_document_taken_as_charge_opens_read_only(batch, conn):
    """The form shows what the ledger allows: a document a batch takes is not edited."""
    b = batch
    assert queries.load_document(conn, b.company_id, b.broker_doc).editable
    post_batch(b, [broker_fee(b)])
    assert not queries.load_document(conn, b.company_id, b.broker_doc).editable
