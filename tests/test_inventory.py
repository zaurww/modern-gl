import sqlite3
from dataclasses import dataclass
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    Inventory,
    IssueLine,
    ReceiptLine,
    TransferLine,
    format_quantity,
    to_quantity,
)
from modern_gl.desktop.inventory_document_page import (
    ACCOUNT,
    ITEM,
    SC1,
    WAREHOUSE,
    InventoryDocumentPage,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_page import InventoryPage, OperationDialog
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, schema_version
from modern_gl.reporting.inventory import (
    has_units,
    item_choices,
    list_inventory_documents,
    receipt_line_choices,
    stock_account_choices,
    stock_balances,
    stock_card,
    unit_choices,
    warehouse_choices,
)
from modern_gl.reporting.reports import trial_balance


@dataclass
class InventoryDemo:
    inventory: Inventory
    company_id: int
    item: int
    other_item: int
    main: int
    reserve: int
    inventory_account: int
    payable_account: int
    expense_account: int
    supplier: int


def test_inventory_migration_upgrades_v6_database(tmp_path):
    path = tmp_path / "v6.gl"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 6:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.close()

    upgraded = connect(path)
    try:
        assert schema_version(upgraded) >= 7
        tables = {
            row[0]
            for row in upgraded.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'inventory_%'"
            )
        }
        assert {"inventory_items", "inventory_documents", "inventory_lines"} <= tables
    finally:
        upgraded.close()


@pytest.fixture
def inventory_demo(ledger, conn) -> InventoryDemo:
    company_id = ledger.create_company("Склад")
    item_kind = ledger.add_subconto_kind(company_id, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(company_id, "warehouse", "Склады")
    counterparty_kind = ledger.add_subconto_kind(company_id, "counterparty", "Контрагенты")
    inventory_account = ledger.add_account(
        company_id,
        "41",
        "Товары",
        subconto=[item_kind, warehouse_kind],
        account_class="asset",
    )
    payable_account = ledger.add_account(
        company_id,
        "60",
        "Поставщики",
        subconto=[counterparty_kind],
        account_class="liability",
    )
    expense_account = ledger.add_account(company_id, "46", "Себестоимость", account_class="expense")
    supplier = ledger.add_subconto_value(company_id, counterparty_kind, "Поставщик")
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(company_id, "шт", "Штука", precision=3)
    item = inventory.add_item(company_id, "Товар A", unit, inventory_account, "A")
    other_item = inventory.add_item(company_id, "Товар B", unit, inventory_account, "B")
    main = inventory.add_warehouse(company_id, "Основной", "MAIN")
    reserve = inventory.add_warehouse(company_id, "Резервный", "RESERVE")
    return InventoryDemo(
        inventory,
        company_id,
        item,
        other_item,
        main,
        reserve,
        inventory_account,
        payable_account,
        expense_account,
        supplier,
    )


def receipt(demo: InventoryDemo, quantity="10", amount="100.00", *, item=None, warehouse=None):
    return demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-10",
        [
            ReceiptLine(
                item or demo.item,
                warehouse or demo.main,
                quantity,
                amount,
            )
        ],
        demo.payable_account,
        [demo.supplier],
        "Поступление",
    )


def test_quantity_is_exact_and_rejects_float():
    assert to_quantity("1 234,567") == 1_234_567_000
    assert format_quantity(to_quantity("140"), 0) == "140"
    with pytest.raises(TypeError):
        to_quantity(1.5)
    with pytest.raises(ValueError, match="больше 6"):
        to_quantity("1.0000001")


def test_multiline_draft_can_be_saved_edited_and_posted(inventory_demo, conn):
    demo = inventory_demo
    document_id = demo.inventory.create_receipt_draft(
        demo.company_id,
        "2026-01-10",
        [
            ReceiptLine(demo.item, demo.main, "2", "20"),
            ReceiptLine(demo.other_item, demo.main, "3", "45"),
        ],
        demo.payable_account,
        [demo.supplier],
        "Черновик поставки",
    )
    assert stock_balances(conn, demo.company_id) == []
    loaded = demo.inventory.load_document(demo.company_id, document_id)
    assert loaded.status == "draft"
    assert [line.quantity for line in loaded.lines] == [
        2 * QUANTITY_FACTOR,
        3 * QUANTITY_FACTOR,
    ]

    demo.inventory.update_receipt_draft(
        demo.company_id,
        document_id,
        "2026-01-11",
        [
            ReceiptLine(demo.item, demo.main, "4", "44"),
            ReceiptLine(demo.other_item, demo.reserve, "1.5", "30"),
        ],
        demo.payable_account,
        [demo.supplier],
        "Исправленная поставка",
    )
    demo.inventory.post_document(demo.company_id, document_id)
    loaded = demo.inventory.load_document(demo.company_id, document_id)
    assert loaded.status == "posted"
    assert loaded.gl_document_id is not None
    balances = {
        (row.item_id, row.warehouse_id): row for row in stock_balances(conn, demo.company_id)
    }
    assert balances[(demo.item, demo.main)].amount == 4_400
    assert balances[(demo.other_item, demo.reserve)].quantity == 1_500_000


def test_posting_failed_draft_remains_editable(inventory_demo, conn):
    demo = inventory_demo
    document_id = demo.inventory.create_issue_draft(
        demo.company_id,
        "2026-01-10",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    with pytest.raises(ValidationError, match="недостаточно товара"):
        demo.inventory.post_document(demo.company_id, document_id)
    loaded = demo.inventory.load_document(demo.company_id, document_id)
    assert loaded.status == "draft"
    assert loaded.lines[0].amount == 0
    assert conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0] == 0


def test_inventory_document_can_be_unposted_edited_and_reposted(inventory_demo, conn):
    demo = inventory_demo
    document_id = receipt(demo, "2", "20")
    gl_document_id = demo.inventory.load_document(demo.company_id, document_id).gl_document_id
    demo.inventory.unpost_document(demo.company_id, document_id)
    loaded = demo.inventory.load_document(demo.company_id, document_id)
    assert loaded.status == "draft"
    assert loaded.gl_document_id is None
    assert stock_balances(conn, demo.company_id) == []
    assert (
        conn.execute("SELECT COUNT(*) FROM documents WHERE id = ?", (gl_document_id,)).fetchone()[0]
        == 0
    )

    demo.inventory.update_receipt_draft(
        demo.company_id,
        document_id,
        "2026-01-11",
        [ReceiptLine(demo.item, demo.main, "3", "36")],
        demo.payable_account,
        [demo.supplier],
    )
    demo.inventory.post_document(demo.company_id, document_id)
    assert stock_balances(conn, demo.company_id)[0].amount == 3_600


def test_issue_and_transfer_drafts_calculate_cost_when_posted(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "10", "100")
    issue = demo.inventory.create_issue_draft(
        demo.company_id,
        "2026-01-11",
        [
            IssueLine(demo.item, demo.main, "2", demo.expense_account),
            IssueLine(demo.item, demo.main, "3", demo.expense_account),
        ],
    )
    demo.inventory.post_document(demo.company_id, issue)
    assert [line.amount for line in demo.inventory.load_document(demo.company_id, issue).lines] == [
        2_000,
        3_000,
    ]
    assert stock_balances(conn, demo.company_id)[0].quantity == 5 * QUANTITY_FACTOR

    demo.inventory.unpost_document(demo.company_id, issue)
    assert [line.amount for line in demo.inventory.load_document(demo.company_id, issue).lines] == [
        0,
        0,
    ]
    assert stock_balances(conn, demo.company_id)[0].quantity == 10 * QUANTITY_FACTOR

    transfer = demo.inventory.create_transfer_draft(
        demo.company_id,
        "2026-01-12",
        [TransferLine(demo.item, demo.main, demo.reserve, "4")],
    )
    demo.inventory.post_document(demo.company_id, transfer)
    balances = {row.warehouse_id: row for row in stock_balances(conn, demo.company_id)}
    assert balances[demo.main].quantity == 6 * QUANTITY_FACTOR
    assert balances[demo.reserve].amount == 4_000


def test_unpost_recalculates_later_issue(inventory_demo, conn):
    demo = inventory_demo
    first = receipt(demo, "5", "50")  # 01-10: 5 pcs for 50.00
    second = demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-11",
        [ReceiptLine(demo.item, demo.main, "10", "300")],
        demo.payable_account,
        [demo.supplier],
    )
    issue = demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "4", demo.expense_account)],
    )
    before = demo.inventory.load_document(demo.company_id, issue)
    assert before.lines[0].amount == 9_333  # 350.00 * 4 / 15 = 93.33

    demo.inventory.unpost_document(demo.company_id, first)

    after = demo.inventory.load_document(demo.company_id, issue)
    assert after.lines[0].amount == 12_000  # only the second receipt is left: 300.00 * 4 / 10
    assert after.gl_document_id == before.gl_document_id  # the GL document keeps its number
    gl_amount = conn.execute(
        "SELECT amount FROM postings WHERE document_id = ?", (after.gl_document_id,)
    ).fetchone()[0]
    assert gl_amount == 12_000
    source = conn.execute(
        "SELECT l.document_id FROM stock_consumptions c "
        "JOIN inventory_lines l ON l.id = c.receipt_line_id WHERE c.issue_line_id = ?",
        (after.lines[0].id,),
    ).fetchall()
    assert [row[0] for row in source] == [second]


def test_catalogs_share_subconto_values(inventory_demo, conn):
    demo = inventory_demo
    item = conn.execute(
        "SELECT i.subconto_value_id, v.name, v.code FROM inventory_items i "
        "JOIN subconto_values v ON v.id = i.subconto_value_id WHERE i.id = ?",
        (demo.item,),
    ).fetchone()
    warehouse = conn.execute(
        "SELECT w.subconto_value_id, v.name FROM warehouses w "
        "JOIN subconto_values v ON v.id = w.subconto_value_id WHERE w.id = ?",
        (demo.main,),
    ).fetchone()
    assert (item["name"], item["code"]) == ("Товар A", "A")
    assert warehouse["name"] == "Основной"


def test_receipt_posts_stock_and_gl_atomically(inventory_demo, conn):
    demo = inventory_demo
    inv_doc = receipt(demo)
    balance = stock_balances(conn, demo.company_id)
    assert len(balance) == 1
    assert (balance[0].quantity, balance[0].amount) == (10 * QUANTITY_FACTOR, 10_000)

    doc = conn.execute(
        "SELECT status, gl_document_id FROM inventory_documents WHERE id = ?", (inv_doc,)
    ).fetchone()
    posting = conn.execute(
        "SELECT * FROM postings WHERE document_id = ?", (doc["gl_document_id"],)
    ).fetchone()
    item_value = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (demo.item,)
    ).fetchone()[0]
    warehouse_value = conn.execute(
        "SELECT subconto_value_id FROM warehouses WHERE id = ?", (demo.main,)
    ).fetchone()[0]
    assert doc["status"] == "posted"
    assert (posting["amount"], posting["dt_sc1"], posting["dt_sc2"], posting["ct_sc1"]) == (
        10_000,
        item_value,
        warehouse_value,
        demo.supplier,
    )


def test_weighted_average_issue(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "10", "100")
    demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-11",
        [ReceiptLine(demo.item, demo.main, "10", "300")],
        demo.payable_account,
        [demo.supplier],
    )
    issue = demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "5", demo.expense_account)],
        "Продажа",
    )
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (15 * QUANTITY_FACTOR, 30_000)
    line = conn.execute(
        "SELECT amount FROM inventory_lines WHERE document_id = ?", (issue,)
    ).fetchone()
    assert line["amount"] == 10_000


def test_issue_cannot_make_negative_stock_and_is_atomic(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "2", "20")
    before_docs = conn.execute("SELECT COUNT(*) FROM inventory_documents").fetchone()[0]
    before_gl = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    with pytest.raises(ValidationError, match="недостаточно товара"):
        demo.inventory.post_issue(
            demo.company_id,
            "2026-01-12",
            [IssueLine(demo.item, demo.main, "3", demo.expense_account)],
        )
    assert conn.execute("SELECT COUNT(*) FROM inventory_documents").fetchone()[0] == before_docs
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before_gl


def test_backdated_receipt_recalculates_later_issue(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "10", "100")  # 01-10: 10.00 a piece
    issue = demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "5", demo.expense_account)],
    )
    gl_document_id = demo.inventory.load_document(demo.company_id, issue).gl_document_id
    assert demo.inventory.load_document(demo.company_id, issue).lines[0].amount == 5_000

    demo.inventory.post_receipt(  # entered later, dated before the issue
        demo.company_id,
        "2026-01-09",
        [ReceiptLine(demo.item, demo.main, "10", "300")],
        demo.payable_account,
        [demo.supplier],
    )

    reissued = demo.inventory.load_document(demo.company_id, issue)
    assert reissued.lines[0].amount == 10_000  # (300.00 + 100.00) / 20 * 5
    assert reissued.gl_document_id == gl_document_id
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (15 * QUANTITY_FACTOR, 30_000)


def test_transfer_preserves_total_and_moves_value(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "10", "125")
    transfer = demo.inventory.post_transfer(
        demo.company_id,
        "2026-01-12",
        [TransferLine(demo.item, demo.main, demo.reserve, "4")],
    )
    balances = {row.warehouse_id: row for row in stock_balances(conn, demo.company_id)}
    assert (balances[demo.main].quantity, balances[demo.main].amount) == (
        6 * QUANTITY_FACTOR,
        7_500,
    )
    assert (balances[demo.reserve].quantity, balances[demo.reserve].amount) == (
        4 * QUANTITY_FACTOR,
        5_000,
    )
    moves = conn.execute(
        "SELECT quantity, amount FROM stock_movements WHERE document_id = ? ORDER BY id",
        (transfer,),
    ).fetchall()
    assert [(r["quantity"], r["amount"]) for r in moves] == [
        (-4 * QUANTITY_FACTOR, -5_000),
        (4 * QUANTITY_FACTOR, 5_000),
    ]


def test_landed_cost_before_issue_increases_stock_value(inventory_demo, conn):
    demo = inventory_demo
    freight = demo.inventory.add_landed_cost_type(demo.company_id, "Доставка", "FREIGHT")
    inv_doc = receipt(demo, "10", "100")
    receipt_line = conn.execute(
        "SELECT id FROM inventory_lines WHERE document_id = ?", (inv_doc,)
    ).fetchone()[0]
    landed = demo.inventory.post_landed_cost(
        demo.company_id,
        "2026-01-15",
        [receipt_line],
        "20",
        demo.payable_account,
        [demo.supplier],
        cost_type_id=freight,
    )
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (10 * QUANTITY_FACTOR, 12_000)
    line = conn.execute(
        "SELECT amount, inventory_amount, expense_amount FROM inventory_lines "
        "WHERE document_id = ?",
        (landed,),
    ).fetchone()
    assert tuple(line) == (2_000, 2_000, 0)
    assert (
        conn.execute(
            "SELECT landed_cost_type_id FROM inventory_documents WHERE id = ?", (landed,)
        ).fetchone()[0]
        == freight
    )


def test_late_landed_cost_splits_stock_and_expense(inventory_demo, conn):
    demo = inventory_demo
    inv_doc = receipt(demo, "10", "100")
    receipt_line = conn.execute(
        "SELECT id FROM inventory_lines WHERE document_id = ?", (inv_doc,)
    ).fetchone()[0]
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "4", demo.expense_account)],
    )
    landed = demo.inventory.post_landed_cost(
        demo.company_id,
        "2026-01-15",
        [receipt_line],
        "20",
        demo.payable_account,
        [demo.supplier],
        "Доставка",
    )
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (6 * QUANTITY_FACTOR, 7_200)
    line = conn.execute(
        "SELECT inventory_amount, expense_amount FROM inventory_lines WHERE document_id = ?",
        (landed,),
    ).fetchone()
    assert tuple(line) == (1_200, 800)

    gl_doc = conn.execute(
        "SELECT gl_document_id FROM inventory_documents WHERE id = ?", (landed,)
    ).fetchone()[0]
    postings = conn.execute(
        "SELECT debit_account_id, credit_account_id, amount FROM postings "
        "WHERE document_id = ? ORDER BY line_no",
        (gl_doc,),
    ).fetchall()
    assert [(p["debit_account_id"], p["credit_account_id"], p["amount"]) for p in postings] == [
        (demo.inventory_account, demo.payable_account, 1_200),
        (demo.expense_account, demo.payable_account, 800),
    ]

    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-20",
        [IssueLine(demo.item, demo.main, "6", demo.expense_account)],
    )
    assert stock_balances(conn, demo.company_id) == []
    osv = {
        row.code: row
        for row in trial_balance(conn, demo.company_id, "2026-01-01", "2026-01-31").rows
    }
    assert osv["46"].turnover_dt == 12_000
    assert osv["41"].closing_dt == 0


def test_landed_cost_allocation_by_value(inventory_demo, conn):
    demo = inventory_demo
    first = receipt(demo, "5", "60")
    second = demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-11",
        [ReceiptLine(demo.other_item, demo.main, "5", "40")],
        demo.payable_account,
        [demo.supplier],
    )
    line_ids = [
        conn.execute(
            "SELECT id FROM inventory_lines WHERE document_id = ?", (document_id,)
        ).fetchone()[0]
        for document_id in (first, second)
    ]
    landed = demo.inventory.post_landed_cost(
        demo.company_id,
        "2026-01-15",
        line_ids,
        "10",
        demo.payable_account,
        [demo.supplier],
        method="value",
    )
    allocations = conn.execute(
        "SELECT item_id, amount FROM inventory_lines WHERE document_id = ? ORDER BY line_no",
        (landed,),
    ).fetchall()
    assert [(row["item_id"], row["amount"]) for row in allocations] == [
        (demo.item, 600),
        (demo.other_item, 400),
    ]


def test_stock_card_has_running_balances(inventory_demo, conn):
    demo = inventory_demo
    receipt(demo, "10", "100")
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "4", demo.expense_account)],
    )
    card = stock_card(conn, demo.company_id, demo.item, demo.main)
    assert [(line.quantity_balance, line.amount_balance) for line in card] == [
        (10 * QUANTITY_FACTOR, 10_000),
        (6 * QUANTITY_FACTOR, 6_000),
    ]


def test_linked_gl_document_must_be_corrected_through_inventory(inventory_demo, conn):
    demo = inventory_demo
    inv_doc = receipt(demo)
    gl_document = conn.execute(
        "SELECT gl_document_id FROM inventory_documents WHERE id = ?", (inv_doc,)
    ).fetchone()[0]
    with pytest.raises(ValidationError, match="через склад"):
        demo.inventory.ledger.unpost(demo.company_id, gl_document)
    with pytest.raises(ValidationError, match="через склад"):
        demo.inventory.ledger.delete_document(demo.company_id, gl_document)
    with pytest.raises(ValidationError, match="через склад"):
        demo.inventory.ledger.reverse(demo.company_id, gl_document, "2026-01-20")


def test_inventory_document_delete_is_atomic_and_respects_dependencies(inventory_demo, conn):
    demo = inventory_demo
    inv_doc = receipt(demo)
    demo.inventory.delete_document(demo.company_id, inv_doc)
    assert stock_balances(conn, demo.company_id) == []
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM inventory_documents WHERE id = ?", (inv_doc,)
        ).fetchone()[0]
        == 0
    )

    inv_doc = receipt(demo)
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    with pytest.raises(ValidationError, match="не проводится складской документ №"):
        demo.inventory.delete_document(demo.company_id, inv_doc)
    assert (
        conn.execute("SELECT status FROM inventory_documents WHERE id = ?", (inv_doc,)).fetchone()[
            0
        ]
        == "posted"
    )


def test_transfer_cannot_be_deleted_after_destination_stock_was_used(inventory_demo):
    demo = inventory_demo
    receipt(demo)
    transfer = demo.inventory.post_transfer(
        demo.company_id,
        "2026-01-11",
        [TransferLine(demo.item, demo.main, demo.reserve, "5")],
    )
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.reserve, "2", demo.expense_account)],
    )
    with pytest.raises(ValidationError, match="недостаточно товара"):
        demo.inventory.delete_document(demo.company_id, transfer)


def test_posted_inventory_rows_are_immutable(inventory_demo, conn):
    inv_doc = receipt(inventory_demo)
    line_id = conn.execute(
        "SELECT id FROM inventory_lines WHERE document_id = ?", (inv_doc,)
    ).fetchone()[0]
    movement_id = conn.execute(
        "SELECT id FROM stock_movements WHERE document_id = ?", (inv_doc,)
    ).fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE inventory_lines SET quantity = 1 WHERE id = ?", (line_id,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM stock_movements WHERE id = ?", (movement_id,))


def test_inventory_page_shows_balance(inventory_demo, conn, qtbot):
    demo = inventory_demo
    receipt(demo, "3", "45")
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
    )
    page = InventoryPage(session)
    qtbot.addWidget(page)
    assert page.model.rowCount() == 1
    assert page.model.index(0, 0).data().endswith("Товар A")
    assert page.model.index(0, 2).data() == "3"
    assert page.model.index(0, 5).data() == "45.00"


def test_multiline_inventory_document_page_posts_rows(inventory_demo, conn, qtbot):
    demo = inventory_demo
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
        working_date=date(2026, 1, 10),
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    page.memo.setText("Две позиции")
    page.model.beginResetModel()
    page.model.rows = [
        InventoryGridRow(
            demo.item,
            demo.main,
            quantity=2 * QUANTITY_FACTOR,
            amount=2_000,
            offset_account_id=demo.payable_account,
            offset_subconto=[demo.supplier, None, None],
        ),
        InventoryGridRow(
            demo.other_item,
            demo.main,
            quantity=3 * QUANTITY_FACTOR,
            amount=4_500,
            offset_account_id=demo.payable_account,
            offset_subconto=[demo.supplier, None, None],
        ),
    ]
    page.model.endResetModel()
    assert page.save(post=True)
    assert page.doc is not None and page.doc.status == "posted"
    assert len(page.doc.lines) == 2
    assert sum(row.amount for row in stock_balances(conn, demo.company_id)) == 6_500


def test_landed_cost_dialog_selects_multiple_receipts(inventory_demo, conn, qtbot):
    demo = inventory_demo
    freight = demo.inventory.add_landed_cost_type(demo.company_id, "Доставка")
    receipt(demo, "5", "60")
    demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-11",
        [ReceiptLine(demo.other_item, demo.main, "5", "40")],
        demo.payable_account,
        [demo.supplier],
    )
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
        working_date=date(2026, 1, 15),
    )
    dialog = OperationDialog(session, demo.inventory, "landed_cost")
    qtbot.addWidget(dialog)
    assert dialog.receipt_lines.count() == 2
    dialog.cost_type.setCurrentIndex(dialog.cost_type.findData(freight))
    for row in range(dialog.receipt_lines.count()):
        dialog.receipt_lines.item(row).setSelected(True)
    dialog.amount.setText("10")
    dialog._post()
    allocations = conn.execute(
        "SELECT amount FROM inventory_lines WHERE document_id = "
        "(SELECT MAX(id) FROM inventory_documents) ORDER BY line_no"
    ).fetchall()
    assert [row["amount"] for row in allocations] == [400, 600]
    assert (
        conn.execute(
            "SELECT landed_cost_type_id FROM inventory_documents "
            "WHERE id = (SELECT MAX(id) FROM inventory_documents)"
        ).fetchone()[0]
        == freight
    )


def test_unfinished_receipt_draft_is_saved_and_completed_before_posting(inventory_demo, conn):
    demo = inventory_demo
    document_id = demo.inventory.create_receipt_draft(
        demo.company_id,
        "2026-01-10",
        [ReceiptLine(demo.item, None, None, None)],
        None,
        (),
        "Не дописан",
    )
    line = demo.inventory.load_document(demo.company_id, document_id).lines[0]
    assert (line.warehouse_id, line.quantity, line.amount, line.offset_account_id) == (
        None,
        0,
        0,
        None,
    )
    with pytest.raises(ValidationError, match="строка 1: не указан склад"):
        demo.inventory.post_document(demo.company_id, document_id)

    demo.inventory.update_receipt_draft(
        demo.company_id,
        document_id,
        "2026-01-10",
        [ReceiptLine(demo.item, demo.main, "2", None)],
        demo.payable_account,
        [demo.supplier],
    )
    with pytest.raises(ValidationError, match="строка 1: не указана сумма"):
        demo.inventory.post_document(demo.company_id, document_id)

    demo.inventory.update_receipt_draft(
        demo.company_id,
        document_id,
        "2026-01-10",
        [ReceiptLine(demo.item, demo.main, "2", "30")],
        demo.payable_account,
        [demo.supplier],
    )
    demo.inventory.post_document(demo.company_id, document_id)
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (2 * QUANTITY_FACTOR, 3_000)


def test_draft_may_be_dated_before_last_posted_document(inventory_demo):
    demo = inventory_demo
    receipt(demo, "10", "100")  # 2026-01-10, 10.00 a piece
    issue = demo.inventory.create_issue_draft(
        demo.company_id,
        "2026-01-05",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    with pytest.raises(ValidationError, match="недостаточно товара"):  # nothing yet on 01-05
        demo.inventory.post_document(demo.company_id, issue)
    demo.inventory.update_issue_draft(
        demo.company_id,
        issue,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    demo.inventory.post_document(demo.company_id, issue)
    assert demo.inventory.load_document(demo.company_id, issue).lines[0].amount == 1_000


def _type_in_cell(qtbot, page: InventoryDocumentPage, row: int, key: str, text: str) -> None:
    index = page.model.index(row, page.model.columns.index(key))
    page.table.setCurrentIndex(index)
    page.table.edit(index)
    editor = page.table.indexWidget(index)
    editor.setText(text)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)


def test_inventory_grid_tab_commits_adds_counterparty_and_saves_unfinished_draft(
    inventory_demo, conn, qtbot, monkeypatch
):
    demo = inventory_demo
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
        working_date=date(2026, 1, 10),
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    page.show()
    model = page.model
    assert model.rows[0].offset_account_id == demo.payable_account
    assert model.rows[0].offset_subconto == [None, None, None]  # no guessed counterparty

    _type_in_cell(qtbot, page, 0, ITEM, "товар b")
    assert model.rows[0].item_id == demo.other_item
    _type_in_cell(qtbot, page, 0, WAREHOUSE, "резерв")
    assert model.rows[0].warehouse_id == demo.reserve
    model.setData(model.index(0, model.columns.index(ACCOUNT)), demo.payable_account)
    _type_in_cell(qtbot, page, 0, SC1, "Новый поставщик")
    qtbot.waitUntil(lambda: model.rows[0].offset_subconto[0] is not None)
    added = session.catalog.value(model.rows[0].offset_subconto[0])
    assert added.name == "Новый поставщик"

    model.insert_row()  # a prefilled trailing row is not a line
    assert page.save(post=False), page.error.text()
    assert page.doc.status == "draft"
    assert len(page.doc.lines) == 1
    line = page.doc.lines[0]
    assert (line.item_id, line.warehouse_id, line.quantity, line.offset_subconto[0]) == (
        demo.other_item,
        demo.reserve,
        0,
        added.id,
    )
    assert not page.save(post=True)
    assert "не указано количество" in page.error.text()


def test_lookups_list_only_this_company(inventory_demo, ledger, conn):
    demo = inventory_demo
    other = ledger.create_company("Другая")
    Inventory(conn, actor="test").add_unit(other, "кг", "Килограмм")
    assert [(c.label, c.unit, c.precision) for c in item_choices(conn, demo.company_id)] == [
        ("A  Товар A", "шт", 3),
        ("B  Товар B", "шт", 3),
    ]
    assert [c.label for c in warehouse_choices(conn, demo.company_id)] == [
        "MAIN  Основной",
        "RESERVE  Резервный",
    ]
    assert [c.label for c in unit_choices(conn, demo.company_id)] == ["шт  Штука"]
    assert [c.id for c in stock_account_choices(conn, demo.company_id)] == [demo.inventory_account]
    assert has_units(conn, other)
    assert not has_units(conn, ledger.create_company("Пустая"))
    assert item_choices(conn, other) == []


def test_receipt_lines_and_document_list(inventory_demo, conn):
    demo = inventory_demo
    document_id = receipt(demo, "10", "100.00")
    [line] = receipt_line_choices(conn, demo.company_id)
    assert (line.number, line.item_name, line.quantity, line.amount) == (
        1,
        "Товар A",
        10 * QUANTITY_FACTOR,
        10_000,
    )
    [summary] = list_inventory_documents(conn, demo.company_id)
    assert (summary.id, summary.doc_type, summary.status, summary.amount) == (
        document_id,
        "receipt",
        "posted",
        10_000,
    )


def test_posting_incomplete_lines_names_the_missing_field(inventory_demo):
    demo = inventory_demo
    inv, cid = demo.inventory, demo.company_id
    with pytest.raises(ValidationError, match=r"строка 1: не указан склад$"):
        inv.post_receipt(
            cid, "2026-01-10", [ReceiptLine(demo.item, None, "1", "10")], demo.payable_account
        )
    with pytest.raises(ValidationError, match="строка 1: не указано количество"):
        inv.post_receipt(
            cid, "2026-01-10", [ReceiptLine(demo.item, demo.main, None, "10")], demo.payable_account
        )
    with pytest.raises(ValidationError, match="строка 1: не указана сумма"):
        inv.post_receipt(
            cid, "2026-01-10", [ReceiptLine(demo.item, demo.main, "1", "")], demo.payable_account
        )
    receipt(demo)
    with pytest.raises(ValidationError, match="строка 1: не указан счёт"):
        inv.post_issue(cid, "2026-01-11", [IssueLine(demo.item, demo.main, "1", None)])
    with pytest.raises(ValidationError, match="строка 1: не указан склад-получатель"):
        inv.post_transfer(cid, "2026-01-11", [TransferLine(demo.item, demo.main, None, "1")])


@pytest.fixture
def receipt_page(inventory_demo, conn, qtbot):
    demo = inventory_demo
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
        working_date=date(2026, 1, 10),
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    return page


def test_excel_lines_paste_into_a_receipt_by_header(inventory_demo, receipt_page):
    """Columns in any order; a price is multiplied by the quantity, a sum is taken as is."""
    demo, model = inventory_demo, receipt_page.model
    receipt_page.paste(
        "Склад\tТовар\tКол-во\tЕд.\tЦена\tСумма\tСубконто\n"
        "Основной\tТовар A\t2\tшт\t1 000,50\t\tПоставщик\n"
        "Резервный\tB\t3,5\tшт\t\t1 500,00\tПоставщик\n"
    )
    assert receipt_page.error.isHidden()
    first, second = model.rows[:2]
    assert (first.item_id, first.warehouse_id) == (demo.item, demo.main)
    assert first.quantity == 2 * QUANTITY_FACTOR
    assert first.amount == 200_100  # 2 × 1 000.50
    assert (second.item_id, second.warehouse_id) == (demo.other_item, demo.reserve)
    assert second.quantity == 3_500_000
    assert second.amount == 150_000
    assert first.offset_subconto[0] == second.offset_subconto[0] == demo.supplier
    assert len(model.to_inputs()) == 2  # complete: can be posted


def test_excel_paste_without_header_follows_the_table(inventory_demo, receipt_page):
    model = receipt_page.model
    receipt_page.paste("Товар A\tОсновной\t2\tшт\t\t300")  # the unit column is skipped
    row = model.rows[0]
    assert (row.item_id, row.warehouse_id) == (inventory_demo.item, inventory_demo.main)
    assert (row.quantity, row.amount) == (2 * QUANTITY_FACTOR, 30_000)


def test_excel_paste_adds_new_items_warehouses_and_subconto(
    inventory_demo, receipt_page, monkeypatch
):
    from modern_gl.desktop.inventory_document_page import NewNamesDialog

    monkeypatch.setattr(NewNamesDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    s, model = receipt_page.s, receipt_page.model
    receipt_page.paste(
        "Товар\tСклад\tКоличество\tЕд.\tСумма\tСубконто\n"
        "Товар C\tНовый склад\t5\tкг\t500\tНовый поставщик\n"
        "Товар C\tНовый склад\t1\tкг\t100\tНовый поставщик\n"
    )
    assert receipt_page.error.isHidden()
    items = {c.label: c for c in item_choices(s.conn, s.company_id)}
    assert items["Товар C"].unit == "кг"  # the pasted unit, made new
    first, second = model.rows[:2]
    assert first.item_id == second.item_id == items["Товар C"].id  # added once
    assert first.warehouse_id == second.warehouse_id is not None
    assert first.offset_subconto[0] == second.offset_subconto[0] is not None
    assert s.catalog.value(first.offset_subconto[0]).name == "Новый поставщик"
    assert first.amount == 50_000


def test_inventory_lines_copy_for_excel_and_back(inventory_demo, receipt_page, qtbot):
    receipt_page.paste("Товар\tСклад\tКоличество\tСумма\nТовар A\tОсновной\t2\t300\n")
    text = receipt_page.model.copy_text(receipt_page._shown)
    other = InventoryDocumentPage(receipt_page.s, doc_type="receipt")
    qtbot.addWidget(other)
    other.paste(text)
    pasted, original = other.model.rows[0], receipt_page.model.rows[0]
    assert (pasted.item_id, pasted.warehouse_id, pasted.quantity, pasted.amount) == (
        original.item_id,
        original.warehouse_id,
        original.quantity,
        original.amount,
    )


def test_posted_receipt_is_edited_in_place_and_later_documents_follow(inventory_demo, conn):
    """1C way: change the price of a posted receipt; the issue and the landed cost after
    it are recalculated, every document keeps its number and the receipt line its id."""
    demo = inventory_demo
    inv_doc = receipt(demo, "10", "100")  # 01-10: 10 pcs for 100.00
    receipt_doc = demo.inventory.load_document(demo.company_id, inv_doc)
    line = receipt_doc.lines[0]
    issue = demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "4", demo.expense_account)],
    )
    landed = demo.inventory.post_landed_cost(
        demo.company_id, "2026-01-15", [line.id], "20", demo.payable_account, [demo.supplier]
    )
    gl_numbers = {
        doc: demo.inventory.load_document(demo.company_id, doc).gl_document_id
        for doc in (inv_doc, issue, landed)
    }

    with demo.inventory.reposting(demo.company_id, inv_doc):
        demo.inventory.update_receipt_draft(
            demo.company_id,
            inv_doc,
            "2026-01-10",
            [ReceiptLine(demo.item, demo.main, "10", "150", line_id=line.id)],
            demo.payable_account,
            [demo.supplier],
        )

    edited = demo.inventory.load_document(demo.company_id, inv_doc)
    assert edited.status == "posted"
    assert edited.lines[0].id == line.id
    # issue: 150.00 * 4 / 10 = 60.00
    assert demo.inventory.load_document(demo.company_id, issue).lines[0].amount == 6_000
    # landed cost 20.00: 6 of 10 still in stock -> 12.00 to stock, 8.00 to expense
    lc_line = demo.inventory.load_document(demo.company_id, landed).lines[0]
    assert (lc_line.inventory_amount, lc_line.expense_amount) == (1_200, 800)
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (6 * QUANTITY_FACTOR, 10_200)  # 90.00 + 12.00
    for doc, gl_id in gl_numbers.items():
        assert demo.inventory.load_document(demo.company_id, doc).gl_document_id == gl_id
    totals = {
        r["document_id"]: r["total"]
        for r in conn.execute(
            "SELECT document_id, SUM(amount) AS total FROM postings GROUP BY document_id"
        )
    }
    assert totals[gl_numbers[inv_doc]] == 15_000
    assert totals[gl_numbers[issue]] == 6_000
    assert totals[gl_numbers[landed]] == 2_000
    actions = [
        r[0]
        for r in conn.execute(
            "SELECT action FROM audit_events WHERE entity = 'inventory_document' "
            "AND entity_id = ? ORDER BY id",
            (inv_doc,),
        )
    ]
    assert actions[-1] == "repost"


def test_failed_repost_changes_nothing(inventory_demo, conn):
    demo = inventory_demo
    inv_doc = receipt(demo, "10", "100")
    line = demo.inventory.load_document(demo.company_id, inv_doc).lines[0]
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "8", demo.expense_account)],
    )
    with (
        pytest.raises(ValidationError, match="не проводится складской документ №"),
        demo.inventory.reposting(demo.company_id, inv_doc),
    ):
        demo.inventory.update_receipt_draft(  # 5 pieces cannot cover the issue of 8
            demo.company_id,
            inv_doc,
            "2026-01-10",
            [ReceiptLine(demo.item, demo.main, "5", "100", line_id=line.id)],
            demo.payable_account,
            [demo.supplier],
        )
    doc = demo.inventory.load_document(demo.company_id, inv_doc)
    assert (doc.status, doc.lines[0].quantity) == ("posted", 10 * QUANTITY_FACTOR)
    balance = stock_balances(conn, demo.company_id)[0]
    assert (balance.quantity, balance.amount) == (2 * QUANTITY_FACTOR, 2_000)


def test_receipt_line_with_landed_cost_cannot_be_removed(inventory_demo):
    demo = inventory_demo
    inv_doc = demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-10",
        [
            ReceiptLine(demo.item, demo.main, "10", "100"),
            ReceiptLine(demo.other_item, demo.main, "5", "50"),
        ],
        demo.payable_account,
        [demo.supplier],
    )
    first, second = demo.inventory.load_document(demo.company_id, inv_doc).lines
    demo.inventory.post_landed_cost(
        demo.company_id, "2026-01-15", [first.id], "20", demo.payable_account, [demo.supplier]
    )
    with (
        pytest.raises(ValidationError, match="распределены дополнительные расходы"),
        demo.inventory.reposting(demo.company_id, inv_doc),
    ):
        demo.inventory.update_receipt_draft(
            demo.company_id,
            inv_doc,
            "2026-01-10",
            [ReceiptLine(demo.other_item, demo.main, "5", "50", line_id=second.id)],
            demo.payable_account,
            [demo.supplier],
        )
    # removing the other line is fine
    with demo.inventory.reposting(demo.company_id, inv_doc):
        demo.inventory.update_receipt_draft(
            demo.company_id,
            inv_doc,
            "2026-01-10",
            [ReceiptLine(demo.item, demo.main, "10", "100", line_id=first.id)],
            demo.payable_account,
            [demo.supplier],
        )
    assert [ln.id for ln in demo.inventory.load_document(demo.company_id, inv_doc).lines] == [
        first.id
    ]


def test_issue_moved_to_an_earlier_date_takes_its_place(inventory_demo):
    demo = inventory_demo
    receipt(demo, "10", "100")  # 01-10: 10.00 a piece
    demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-20",
        [ReceiptLine(demo.item, demo.main, "10", "300")],  # 30.00 a piece
        demo.payable_account,
        [demo.supplier],
    )
    issue = demo.inventory.post_issue(
        demo.company_id,
        "2026-01-25",
        [IssueLine(demo.item, demo.main, "5", demo.expense_account)],
    )
    assert demo.inventory.load_document(demo.company_id, issue).lines[0].amount == 10_000
    line = demo.inventory.load_document(demo.company_id, issue).lines[0]
    with demo.inventory.reposting(demo.company_id, issue):
        demo.inventory.update_issue_draft(
            demo.company_id,
            issue,
            "2026-01-15",  # before the expensive receipt
            [IssueLine(demo.item, demo.main, "5", demo.expense_account, line_id=line.id)],
        )
    assert demo.inventory.load_document(demo.company_id, issue).lines[0].amount == 5_000
