import sqlite3
from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCompleter, QDialog, QLabel, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    STANDARD_VAT_RATE,
    Inventory,
    IssueLine,
    ReceiptLine,
    TransferLine,
    UsualUnit,
    format_quantity,
    to_quantity,
    vat_of,
)
from modern_gl.desktop.inventory_document_page import (
    ACCOUNT,
    AMOUNT,
    ITEM,
    ITEM_MIN,
    SC1,
    VAT,
    WAREHOUSE,
    InventoryDocumentPage,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_page import (
    InventoryPage,
    InventorySettingsDialog,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import money
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, schema_version
from modern_gl.reporting.inventory import (
    has_units,
    item_choices,
    item_name,
    last_receipts,
    list_inventory_documents,
    receipt_line_choices,
    stock_account_choices,
    stock_balances,
    stock_card,
    unit_choices,
    warehouse_choices,
)
from modern_gl.reporting.reports import trial_balance
from tests.helpers.inventory import InventoryDemo


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


def test_inventory_document_in_closed_period_is_not_unposted(inventory_demo, ledger):
    demo = inventory_demo
    document_id = receipt(demo)
    ledger.set_closed_through(demo.company_id, "2026-01-31")
    with pytest.raises(
        PeriodClosedError, match=r"складской документ №1 от 10\.01\.2026: период закрыт по 31\.01"
    ):
        demo.inventory.unpost_document(demo.company_id, document_id)


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


def test_item_name_is_read_within_the_company(inventory_demo, ledger, conn):
    """The name of an item by its id; another company's id gives nothing."""
    demo = inventory_demo
    assert item_name(conn, demo.company_id, demo.item) == "Товар A"
    other = ledger.create_company("Другая")
    assert item_name(conn, other, demo.item) == ""
    assert item_name(conn, demo.company_id, 999_999) == ""


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


def test_stock_card_and_last_receipts_name_where_goods_came_from(inventory_demo, conn):
    demo = inventory_demo
    demo.inventory.post_receipt(  # 10 pcs for 100.00 by a customs declaration
        demo.company_id,
        "2026-01-10",
        [ReceiptLine(demo.item, demo.main, "10", "100.00")],
        demo.payable_account,
        [demo.supplier],
        invoice="12345",
        invoice_kind="customs",
    )
    demo.inventory.post_transfer(
        demo.company_id, "2026-01-11", [TransferLine(demo.item, demo.main, demo.reserve, "4")]
    )
    card = stock_card(conn, demo.company_id, demo.item, demo.main)
    received, moved = (line.source for line in card)
    assert (received.doc_type, received.invoice, received.invoice_kind) == (
        "receipt",
        "12345",
        "customs",
    )
    assert received.counterparty == "Поставщик"
    assert (moved.movement_type, moved.other_warehouse) == ("transfer_out", "Резервный")
    # 10 in at 10.00 each, 4 out: 6 pcs worth 60.00 stay
    assert (card[-1].quantity_balance, card[-1].amount_balance) == (6 * QUANTITY_FACTOR, 6_000)

    sources = last_receipts(conn, demo.company_id)
    assert sources[(demo.item, demo.main)].source.invoice == "12345"
    reserve = sources[(demo.item, demo.reserve)]
    assert (reserve.doc_date, reserve.source.movement_type) == ("2026-01-11", "transfer_in")
    assert reserve.source.other_warehouse == "Основной"


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


def test_marked_documents_are_deleted_all_or_none(inventory_demo, ledger, conn):
    """Two receipts of 10.01 (10 pcs, 100.00 each) and a draft of 20.01; closed through
    31.01 the first receipt keeps all three. Open again, all three go: no stock left."""
    demo = inventory_demo
    first, second = receipt(demo), receipt(demo)
    draft = demo.inventory.create_receipt_draft(
        demo.company_id,
        "2026-01-20",
        [ReceiptLine(demo.item, demo.main, "1", "10.00")],
        demo.payable_account,
        [demo.supplier],
        "Черновик",
    )
    ledger.set_closed_through(demo.company_id, "2026-01-31")
    with pytest.raises(PeriodClosedError, match="складской документ №1"):
        demo.inventory.delete_documents(demo.company_id, [draft, first, second])
    count = "SELECT COUNT(*) FROM inventory_documents WHERE company_id = ?"
    assert conn.execute(count, (demo.company_id,)).fetchone()[0] == 3
    assert stock_balances(conn, demo.company_id)[0].amount == 20_000
    ledger.set_closed_through(demo.company_id, None)
    demo.inventory.delete_documents(demo.company_id, [draft, first, second])
    assert conn.execute(count, (demo.company_id,)).fetchone()[0] == 0
    assert stock_balances(conn, demo.company_id) == []


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
    assert page.model.rowCount() == 2
    assert page.model.index(0, 0).data().endswith("Товар A")
    assert page.model.index(0, 2).data() == "Покупка · 10.01.2026"  # where it came from
    assert page.model.index(0, 3).data() == "3"
    assert page.model.index(0, 6).data() == "45.00"
    # an item with nothing in stock is listed too, without a warehouse or a quantity
    assert page.model.index(1, 0).data().endswith("Товар B")
    assert page.model.index(1, 1).data() == "" and page.model.index(1, 3).data() == ""
    page._toggle_idle()  # «⋯ → Товары без остатка»: hidden, remembered
    assert page.model.rowCount() == 1
    page._toggle_idle()
    page.search.setText("товар b")  # the search: by name, code, warehouse, group
    assert page.model.rowCount() == 1 and page.model.index(0, 0).data().endswith("Товар B")


def test_inventory_page_shows_the_chosen_items_movements(inventory_demo, conn, qtbot):
    demo = inventory_demo
    receipt(demo, "3", "45")
    demo.inventory.post_issue(
        demo.company_id,
        "2026-01-12",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    demo.inventory.create_issue_draft(
        demo.company_id,
        "2026-01-13",
        [IssueLine(demo.item, demo.main, "1", demo.expense_account)],
    )
    session = Session(
        conn, demo.inventory.ledger, demo.company_id, "Склад", Catalog(conn, demo.company_id)
    )
    page = InventoryPage(session)
    qtbot.addWidget(page)
    assert page.card_stack.currentWidget() is page.card_empty  # nothing chosen: the hint
    page.table.selectRow(0)
    assert page.below_title.text() == "Товар A · Основной"
    card = page.card_model
    assert [card.index(r, 2).data() for r in range(card.rowCount())] == [
        "Покупка · Поставщик",
        "Списание",
    ]
    # 3 in for 45.00, 1 out at 15.00: 2 stay worth 30.00
    assert [card.index(r, 5).data() for r in range(card.rowCount())] == ["3", "2"]
    assert card.index(1, 6).data() == "30.00"
    with qtbot.waitSignal(page.open_inventory_document) as opened:
        page.card.doubleClicked.emit(card.index(0, 0))
    assert opened.args == [card.rows[0].document_id]

    page.refresh()  # the same row stays chosen
    assert page.chosen_balance() is not None
    assert page.documents_button.text() == "Документы · черновиков: 1"
    assert not page.remove.isVisibleTo(page)  # deleting is for the documents' view
    page.documents_button.click()
    assert page.below.currentWidget() is page.documents_page
    assert page.remove.isVisibleTo(page)

    with qtbot.waitSignal(page.new_inventory_document) as new:
        page.operation_buttons["receipt"].click()  # a purchase from the warehouse itself
    assert new.args == ["receipt"]


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


def test_inventory_account_cell_lists_a_group_and_holds_on_it(inventory_demo, ledger, conn, qtbot):
    demo = inventory_demo
    ledger.add_account(demo.company_id, "76", "Прочие расчёты", is_group=True)
    for code, name in (("76.1", "С подотчётными"), ("76.2", "С прочими")):
        ledger.add_account(demo.company_id, code, name, parent="76", account_class="liability")
    catalog = Catalog(conn, demo.company_id)
    session = Session(
        conn,
        demo.inventory.ledger,
        demo.company_id,
        "Склад",
        catalog,
        working_date=date(2026, 1, 10),
    )
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    page.show()
    group = catalog.by_code["76"]
    subs = catalog.subaccounts(group)
    assert [a.code for a in subs] == ["76.1", "76.2"]
    index = page.model.index(0, page.model.columns.index(ACCOUNT))
    page.table.setCurrentIndex(index)
    page.table.edit(index)
    editor = page.table.indexWidget(index)
    editor.setText(group.code)
    editor.textEdited.emit(editor.text())
    popup = editor.findChild(QCompleter).popup()
    assert popup.model().rowCount() == len(subs)
    assert not popup.currentIndex().isValid()  # not the first subaccount behind the back

    qtbot.keyClick(editor, Qt.Key.Key_Return)  # a group: stays in the cell
    QApplication.processEvents()
    assert page.model.rows[0].offset_account_id == demo.payable_account  # unchanged
    assert page.table.indexWidget(index) is editor
    assert f"{group.code} — группа" in page.error.text()
    assert popup.currentIndex().row() == 0
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert page.model.rows[0].offset_account_id == subs[0].id


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
    # the issue costs 150.00 × 4 / 10 = 60.00
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


# ---- VAT in a receipt (stage 2, D33) ----------------------------------------------


@pytest.fixture
def vat_demo(inventory_demo, ledger) -> tuple[InventoryDemo, int]:
    demo = inventory_demo
    counterparty_kind = ledger.subconto_kind_id(demo.company_id, "counterparty")
    vat_account = ledger.add_account(
        demo.company_id,
        "19",
        "НДС по приобретённым ценностям",
        subconto=[counterparty_kind],
        account_class="asset",
    )
    ledger.set_account_role(demo.company_id, INPUT_VAT, vat_account)
    return demo, vat_account


def vat_receipt(demo: InventoryDemo, lines) -> int:
    return demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-10",
        lines,
        demo.payable_account,
        [demo.supplier],
        "Поступление с НДС",
        vat_rate=STANDARD_VAT_RATE,
    )


def test_vat_of_rounds_to_minor_units():
    assert vat_of(10_000, 1800) == 1_800  # 100.00 * 18% = 18.00
    assert vat_of(3_333, 1800) == 600  # 33.33 * 18% = 5.9994 -> 6.00
    assert vat_of(25, 1800) == 5  # 0.25 * 18% = 0.045 -> 0.05 (half away from zero)
    assert vat_of(10_000, None) == 0
    assert vat_of(10_000, 0) == 0


def test_receipt_vat_posts_to_the_input_vat_account_per_supplier(vat_demo, conn):
    """Two lines 100.00 + 50.00 without VAT, VAT 18.00 + 9.00: the stock is worth 150.00,
    one posting Dt 19 [supplier] / Ct 60 [supplier] 27.00, the supplier is owed 177.00."""
    demo, vat_account = vat_demo
    inv_doc = vat_receipt(
        demo,
        [
            ReceiptLine(demo.item, demo.main, "10", "100", vat_amount="18"),
            ReceiptLine(demo.other_item, demo.main, "5", "50", vat_amount="9"),
        ],
    )
    doc = demo.inventory.load_document(demo.company_id, inv_doc)
    assert doc.vat_rate == STANDARD_VAT_RATE
    assert [line.vat_amount for line in doc.lines] == [1_800, 900]
    assert sum(b.amount for b in stock_balances(conn, demo.company_id)) == 15_000

    vat_postings = conn.execute(
        "SELECT * FROM postings WHERE document_id = ? AND debit_account_id = ?",
        (doc.gl_document_id, vat_account),
    ).fetchall()
    assert len(vat_postings) == 1
    vat = vat_postings[0]
    assert (vat["credit_account_id"], vat["amount"], vat["dt_sc1"], vat["ct_sc1"]) == (
        demo.payable_account,
        2_700,
        demo.supplier,
        demo.supplier,
    )
    owed = conn.execute(
        "SELECT SUM(amount) FROM postings WHERE document_id = ? AND credit_account_id = ?",
        (doc.gl_document_id, demo.payable_account),
    ).fetchone()[0]
    assert owed == 17_700


def test_receipt_vat_is_split_by_supplier(vat_demo, ledger, conn):
    demo, vat_account = vat_demo
    kind = ledger.subconto_kind_id(demo.company_id, "counterparty")
    other = ledger.add_subconto_value(demo.company_id, kind, "Другой поставщик")
    inv_doc = demo.inventory.post_receipt(
        demo.company_id,
        "2026-01-10",
        [
            ReceiptLine(demo.item, demo.main, "1", "10", vat_amount="1.80"),
            ReceiptLine(
                demo.item,
                demo.main,
                "1",
                "20",
                credit_account_id=demo.payable_account,
                credit_subconto=[other],
                vat_amount="3.60",
            ),
        ],
        demo.payable_account,
        [demo.supplier],
        vat_rate=STANDARD_VAT_RATE,
    )
    gl_id = demo.inventory.load_document(demo.company_id, inv_doc).gl_document_id
    rows = conn.execute(
        "SELECT dt_sc1, amount FROM postings WHERE document_id = ? AND debit_account_id = ? "
        "ORDER BY amount",
        (gl_id, vat_account),
    ).fetchall()
    assert [(r["dt_sc1"], r["amount"]) for r in rows] == [(demo.supplier, 180), (other, 360)]


def test_receipt_vat_needs_the_input_vat_account_setting(inventory_demo, conn):
    demo = inventory_demo
    before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    with pytest.raises(ValidationError, match="настройках склада"):
        vat_receipt(demo, [ReceiptLine(demo.item, demo.main, "10", "100", vat_amount="18")])
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before
    assert stock_balances(conn, demo.company_id) == []
    receipt(demo)  # without VAT the same receipt posts: the setting is needed only for VAT


def test_opening_balance_has_no_vat(vat_demo):
    demo, _ = vat_demo
    with pytest.raises(ValidationError, match="только в поступлении"):
        demo.inventory.post_receipt(
            demo.company_id,
            "2026-01-01",
            [ReceiptLine(demo.item, demo.main, "1", "10", vat_amount="1.80")],
            demo.payable_account,
            [demo.supplier],
            opening=True,
        )


def test_editing_posted_receipt_vat_rewrites_its_gl_document(vat_demo, conn):
    demo, vat_account = vat_demo
    inv_doc = vat_receipt(demo, [ReceiptLine(demo.item, demo.main, "10", "100", vat_amount="18")])
    line = demo.inventory.load_document(demo.company_id, inv_doc).lines[0]
    with demo.inventory.reposting(demo.company_id, inv_doc):
        demo.inventory.update_receipt_draft(
            demo.company_id,
            inv_doc,
            "2026-01-10",
            [ReceiptLine(demo.item, demo.main, "10", "100", line_id=line.id)],
            demo.payable_account,
            [demo.supplier],
            vat_rate=None,  # the supplier turned out not to be a VAT payer
        )
    doc = demo.inventory.load_document(demo.company_id, inv_doc)
    assert (doc.status, doc.vat_rate, doc.lines[0].vat_amount) == ("posted", None, 0)
    vat = conn.execute(
        "SELECT COUNT(*) FROM postings WHERE document_id = ? AND debit_account_id = ?",
        (doc.gl_document_id, vat_account),
    ).fetchone()[0]
    assert vat == 0


def test_account_role_must_be_a_posting_account(vat_demo, ledger):
    demo, _ = vat_demo
    group = ledger.add_account(demo.company_id, "68", "Налоги", is_group=True)
    with pytest.raises(ValidationError):
        ledger.set_account_role(demo.company_id, INPUT_VAT, group)
    with pytest.raises(ValidationError):
        ledger.set_account_role(demo.company_id, "no_such_role", demo.payable_account)
    ledger.set_account_role(demo.company_id, INPUT_VAT, None)
    assert ledger.account_role(demo.company_id, INPUT_VAT) is None


@pytest.mark.parametrize(("template", "code"), [("classic", "19"), ("1c77", "19.3")])
def test_chart_template_sets_the_input_vat_account(ledger, template, code):
    company_id = ledger.create_company(template)
    apply_chart_template(ledger, company_id, template, "ru")
    assert ledger.account_role(company_id, INPUT_VAT) == ledger.account_id(company_id, code)


def test_migration_sets_input_vat_for_existing_companies(tmp_path):
    path = tmp_path / "v9.gl"
    old = sqlite3.connect(path, isolation_level=None)
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 9:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.execute("INSERT INTO companies (name, created_at) VALUES ('A', '2026-01-01')")
    old.execute(
        "INSERT INTO accounts (company_id, code, name, account_class) "
        "VALUES (1, '19', 'НДС', 'asset')"
    )
    old.close()

    upgraded = connect(path)
    try:
        roles = upgraded.execute("SELECT company_id, role FROM account_roles").fetchall()
        assert [tuple(r) for r in roles] == [(1, INPUT_VAT)]
    finally:
        upgraded.close()


def vat_page(demo: InventoryDemo, conn, qtbot) -> InventoryDocumentPage:
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


def test_receipt_page_calculates_vat_until_it_is_typed(vat_demo, conn, qtbot):
    demo, vat_account = vat_demo
    page = vat_page(demo, conn, qtbot)
    model = page.model
    vat_column = model.columns.index(VAT)
    assert page._chosen_vat_rate() == STANDARD_VAT_RATE  # the company has a VAT account
    assert not page.table.isColumnHidden(vat_column)
    model.rows = [
        InventoryGridRow(
            demo.item,
            demo.main,
            quantity=QUANTITY_FACTOR,
            offset_account_id=demo.payable_account,
            offset_subconto=[demo.supplier, None, None],
        )
        for _ in range(2)
    ]
    model.setData(model.index(0, model.columns.index(AMOUNT)), 10_000)
    assert model.rows[0].vat_amount == 1_800  # 100.00 * 18%
    model.setData(model.index(0, vat_column), 2_000)  # the invoice says 20.00
    model.setData(model.index(0, model.columns.index(AMOUNT)), 20_000)
    assert model.rows[0].vat_amount == 2_000  # typed: stays
    model.setData(model.index(0, vat_column), None)  # cleared: from the rate again
    assert model.rows[0].vat_amount == 3_600  # 200.00 * 18%
    model.setData(model.index(1, model.columns.index(AMOUNT)), 5_000)
    assert model.rows[1].vat_amount == 900
    # 200.00 + 50.00 without VAT, VAT 36.00 + 9.00
    assert (page.vat_total.text(), page.total.text()) == (money(4_500), money(29_500))

    page.vat_rate.setCurrentIndex(page.vat_rate.findData(None))
    page._vat_rate_changed()
    assert [row.vat_amount for row in model.rows] == [None, None]
    assert page.table.isColumnHidden(vat_column)
    assert page.total.text() == money(25_000)

    page.vat_rate.setCurrentIndex(page.vat_rate.findData(STANDARD_VAT_RATE))
    page._vat_rate_changed()
    assert page.save(post=True)
    assert page.doc is not None and page.doc.vat_rate == STANDARD_VAT_RATE
    assert [line.vat_amount for line in page.doc.lines] == [3_600, 900]
    assert not any(row.vat_typed for row in page.model.rows)
    vat = conn.execute(
        "SELECT SUM(amount) FROM postings WHERE document_id = ? AND debit_account_id = ?",
        (page.doc.gl_document_id, vat_account),
    ).fetchone()[0]
    assert vat == 4_500


def test_receipt_page_without_vat_account_starts_without_vat(inventory_demo, conn, qtbot):
    page = vat_page(inventory_demo, conn, qtbot)
    assert page._chosen_vat_rate() is None
    assert page.table.isColumnHidden(page.model.columns.index(VAT))
    assert page.vat_total.isHidden()


def test_inventory_settings_choose_the_input_vat_account(vat_demo, conn, qtbot):
    demo, vat_account = vat_demo
    session = Session(
        conn, demo.inventory.ledger, demo.company_id, "Склад", Catalog(conn, demo.company_id)
    )
    dialog = InventorySettingsDialog(session)
    qtbot.addWidget(dialog)
    assert dialog.input_vat.currentData() == vat_account
    dialog.input_vat.setCurrentIndex(dialog.input_vat.findData(demo.expense_account))
    dialog._save()
    assert demo.inventory.ledger.account_role(demo.company_id, INPUT_VAT) == demo.expense_account


def test_a_recalculation_reads_the_catalog_once_and_forgets_it(inventory_demo):
    """Debt 6: while later documents are recalculated an item is read once, not for every
    line of every document; afterwards it is read afresh (a change of it is seen)."""
    demo = inventory_demo
    inv = demo.inventory
    receipt(demo, "5", "50")  # 10.01
    for day in ("2026-01-12", "2026-01-13", "2026-01-14"):
        inv.post_issue(
            demo.company_id, day, [IssueLine(demo.item, demo.main, "1", demo.expense_account)]
        )
    reads: list[int] = []
    read_item = inv._read_item

    def counted(company_id: int, item_id: int):
        reads.append(item_id)
        return read_item(company_id, item_id)

    inv._read_item = counted  # type: ignore[method-assign]
    inv.post_receipt(  # 05.01: the receipt of 10.01 and the three issues are recalculated
        demo.company_id,
        "2026-01-05",
        [ReceiptLine(demo.item, demo.main, "5", "100")],
        demo.payable_account,
        [demo.supplier],
    )
    # once for the new draft, once for the five documents in order (each read it before)
    assert reads == [demo.item, demo.item]
    assert inv._kept is None
    inv.post_issue(
        demo.company_id, "2026-01-15", [IssueLine(demo.item, demo.main, "1", demo.expense_account)]
    )
    assert len(reads) > 2  # read again: nothing is kept between scenarios


@pytest.mark.parametrize("doc_type", ["receipt", "sale", "incoming", "issue", "transfer"])
def test_a_warehouse_document_fits_a_laptop_screen(inventory_demo, conn, qtbot, doc_type):
    """Was 1 591 px: the line of keys under the table did not wrap. With the sidebar
    (250 px) a document fits a 1 280 px screen — a 1 920 px laptop at 150 %."""
    demo = inventory_demo
    session = Session(
        conn, demo.inventory.ledger, demo.company_id, "Склад", Catalog(conn, demo.company_id)
    )
    page = InventoryDocumentPage(session, doc_type=doc_type)
    qtbot.addWidget(page)
    assert page.minimumSizeHint().width() <= 1030
    page.resize(1030, 700)
    page.show()
    # the name is not crushed to «Тов»: the other columns scroll
    assert page.table.columnWidth(page.model.columns.index(ITEM)) >= ITEM_MIN


def test_the_landed_cost_page_fits_a_laptop_screen(inventory_demo, conn, qtbot):
    from modern_gl.desktop.landed_cost_page import LandedCostPage

    demo = inventory_demo
    session = Session(
        conn, demo.inventory.ledger, demo.company_id, "Склад", Catalog(conn, demo.company_id)
    )
    page = LandedCostPage(session)
    qtbot.addWidget(page)
    assert page.minimumSizeHint().width() <= 1030


def test_a_first_item_needs_nothing_set_up_before_it(ledger, conn):
    """A new company has no unit and no warehouse (was: «Сначала добавьте единицу
    измерения»). The item dialog offers the usual units; saving the first item makes the
    unit chosen and «Основной склад» in one go; the next item takes the same unit by its
    code and no second warehouse is made."""
    from modern_gl.application.inventory import UsualUnit
    from modern_gl.reporting.inventory import unit_choices, warehouse_choices

    cid = ledger.create_company("Новая")
    kind = ledger.add_subconto_kind(cid, "item", "Товары")
    place = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    stock = ledger.add_account(cid, "41", "Товары", subconto=[kind, place], account_class="asset")
    inventory = Inventory(conn, actor="test")
    pieces = UsualUnit("шт", "Штука", 0)
    paper = inventory.add_new_item(cid, "Бумага", pieces, stock, first_warehouse="Основной склад")
    pens = inventory.add_new_item(cid, "Ручка", pieces, stock, first_warehouse="Основной склад")
    assert [c.label for c in unit_choices(conn, cid)] == ["шт  Штука"]
    assert [c.label for c in warehouse_choices(conn, cid)] == ["Основной склад"]
    units = {
        r[0]
        for r in conn.execute(
            "SELECT unit_id FROM inventory_items WHERE company_id = ? AND id IN (?, ?)",
            (cid, paper, pens),
        )
    }
    assert len(units) == 1
    # a name that is not valid makes nothing: no unit, no warehouse left behind
    other = ledger.create_company("Другая")
    k2 = ledger.add_subconto_kind(other, "item", "Товары")
    w2 = ledger.add_subconto_kind(other, "warehouse", "Склады")
    s2 = ledger.add_account(other, "41", "Товары", subconto=[k2, w2], account_class="asset")
    with pytest.raises(ValidationError):
        inventory.add_new_item(other, " ", pieces, s2, first_warehouse="Основной склад")
    assert unit_choices(conn, other) == [] and warehouse_choices(conn, other) == []


def test_the_item_dialog_of_a_new_company_offers_the_usual_units(ledger, conn, qtbot):
    """No unit, no warehouse yet: the dialog lists the usual units («шт» first) and says
    the warehouse it will make; saved, the item is there with «шт» and «Основной склад»."""
    from modern_gl.desktop.inventory_page.dialogs import ItemDialog
    from modern_gl.reporting.inventory import unit_choices, warehouse_choices

    cid = ledger.create_company("Новая")
    kind = ledger.add_subconto_kind(cid, "item", "Товары")
    place = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    ledger.add_account(cid, "41", "Товары", subconto=[kind, place], account_class="asset")
    session = Session(conn, ledger, cid, "Новая", Catalog(conn, cid))
    dialog = ItemDialog(session, Inventory(conn, actor="test"), name="Бумага А4")
    qtbot.addWidget(dialog)
    units = [dialog.units.itemText(i) for i in range(dialog.units.count())]
    assert units == [
        "шт  Штука",
        "кг  Килограмм",
        "л  Литр",
        "м  Метр",
        "м²  Квадратный метр",
        "уп.  Упаковка",
    ]
    notes = [label.text() for label in dialog.findChildren(QLabel)]
    assert "Вместе с товаром появится склад «Основной склад»" in notes
    dialog._save()
    assert dialog.item_id is not None
    assert [c.label for c in unit_choices(conn, cid)] == ["шт  Штука"]
    assert [c.label for c in warehouse_choices(conn, cid)] == ["Основной склад"]


def test_the_empty_warehouse_says_what_to_do_next(ledger, conn, qtbot):
    """Was text only («Добавьте товар и склад…», the warehouse hidden in «⋯»). No item:
    «+ Товар», «+ Покупка», «Начальные остатки» right there; items without stock: the
    purchase and the opening stock; for viewing only — no buttons (D80)."""
    cid = ledger.create_company("Новая")
    kind = ledger.add_subconto_kind(cid, "item", "Товары")
    place = ledger.add_subconto_kind(cid, "warehouse", "Склады")
    stock = ledger.add_account(cid, "41", "Товары", subconto=[kind, place], account_class="asset")
    session = Session(conn, ledger, cid, "Новая", Catalog(conn, cid))
    page = InventoryPage(session)
    qtbot.addWidget(page)
    page.show()
    asked: list[str] = []
    page.new_inventory_document.connect(asked.append)
    page.add_item = lambda: asked.append("item")  # the dialog itself: tested above

    def shown() -> list[str]:
        return [b.text() for b in page.empty.buttons if b.isVisibleTo(page)]

    assert page.empty.title.text() == "На складе пока пусто"
    assert shown() == ["+ Товар", "+ Покупка", "Начальные остатки"]
    # nothing to choose yet: not «Выберите товар»
    assert page.card_empty.title.text() == "Движений пока нет"
    for b in page.empty.buttons:
        b.click()
    assert asked == ["item", "receipt", "opening"]

    Inventory(conn, actor="test").add_new_item(cid, "Бумага", UsualUnit("шт", "Штука", 0), stock)
    page.refresh()  # the new item is listed at once, with nothing in stock
    assert page.model.rowCount() == 1 and page.model.index(0, 0).data() == "Бумага"
    page._toggle_idle()  # without the items with nothing in stock: what to do next
    assert page.empty.title.text() == "Остатков пока нет"
    assert shown() == ["+ Покупка", "Начальные остатки"]

    viewing = Session(conn, ledger, cid, "Новая", Catalog(conn, cid), read_only=True)
    view = InventoryPage(viewing)
    qtbot.addWidget(view)
    view.show()
    assert [b for b in view.empty.buttons if b.isVisibleTo(view)] == []
