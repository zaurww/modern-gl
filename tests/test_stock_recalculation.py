"""Recalculating the warehouse from a date (debt 6): balances and the receipts still to be
consumed are kept in memory for the whole run instead of being summed again for every
line. Whatever is kept, the run must store exactly what posting one by one stored."""

from __future__ import annotations

import pytest

from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import create_year_demo
from modern_gl.infrastructure.db import connect

STORED = {
    "stock_movements": "document_id, line_id, item_id, warehouse_id, quantity, amount",
    "stock_consumptions": "document_id, issue_line_id, receipt_line_id, quantity",
    "inventory_lines": "id, amount, inventory_amount, expense_amount, cost_account_id",
    "postings": "document_id, line_no, debit_account_id, credit_account_id, amount",
}


@pytest.fixture(scope="module")
def year():
    conn = connect(":memory:")
    ledger = Ledger(conn)
    cid = create_year_demo(ledger)
    ledger.set_closed_through(cid, None)  # the whole year, the closed half too
    yield conn, cid
    conn.close()


def stored(conn, cid, first: int) -> dict[str, list[tuple]]:
    """What the warehouse stored — but the GL document of `first` itself: taken out and
    posted back, it is a new one."""
    own = conn.execute(
        "SELECT gl_document_id FROM inventory_documents WHERE id = ?", (first,)
    ).fetchone()[0]
    return {
        table: [
            tuple(r)
            for r in conn.execute(
                f"SELECT {columns} FROM {table} WHERE company_id = ? "
                f"AND document_id IS DISTINCT FROM ? ORDER BY {columns}"
                if table == "postings"
                else f"SELECT {columns} FROM {table} WHERE company_id = ? ORDER BY {columns}",
                (cid, own) if table == "postings" else (cid,),
            )
        ]
        for table, columns in STORED.items()
    }


def test_a_whole_year_recalculated_stores_what_posting_one_by_one_stored(year):
    """The demo year was posted document by document; taking its first warehouse
    document out (every later one recalculated without it) and posting it back (every
    later one recalculated again) brings every movement, consumption, cost and posting
    back as they were."""
    conn, cid = year
    first = conn.execute(
        "SELECT id FROM inventory_documents WHERE company_id = ? AND status = 'posted' "
        "AND doc_type <> 'opening' ORDER BY doc_date, number LIMIT 1",
        (cid,),
    ).fetchone()["id"]
    before = stored(conn, cid, first)
    inventory = Inventory(conn)
    inventory.unpost_document(cid, first)
    assert stored(conn, cid, first) != before
    inventory.post_document(cid, first)
    assert stored(conn, cid, first) == before
