"""What a document takes that the warehouse does not have on its day — the goods came
before their papers (D154). The page offers a purchase «ждёт e-qaimə» of it: at the last
price, from the last supplier; stock never goes below zero."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.inventory.amounts import unit_price
from modern_gl.infrastructure.db import Connection

# the documents that take goods from a warehouse
TAKING = ("issue", "sale", "transfer", "purchase_return")


@dataclass(frozen=True)
class Shortage:
    item_id: int
    warehouse_id: int
    missing: int  # millionths of the item's unit
    last_price: int | None  # per unit, minor units: the last purchase's
    supplier_account_id: int | None  # the last purchase's settlement account
    supplier_subconto: tuple[int | None, int | None, int | None]


def document_shortages(conn: Connection, company_id: int, document_id: int) -> list[Shortage]:
    """Each item and warehouse the document takes more of than the posted documents
    leave there on its day."""
    doc = conn.execute(
        "SELECT doc_date, doc_type FROM inventory_documents WHERE company_id = ? AND id = ?",
        (company_id, document_id),
    ).fetchone()
    if doc is None or doc["doc_type"] not in TAKING:
        return []
    needed = conn.execute(
        """
        SELECT item_id, warehouse_id, SUM(quantity) AS quantity
        FROM inventory_lines
        WHERE company_id = ? AND document_id = ? AND item_id IS NOT NULL
          AND warehouse_id IS NOT NULL AND quantity > 0
        GROUP BY item_id, warehouse_id
        ORDER BY MIN(line_no)
        """,
        (company_id, document_id),
    ).fetchall()
    result = []
    for row in needed:
        available = conn.execute(
            """
            SELECT COALESCE(SUM(m.quantity), 0) FROM stock_movements m
            JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
            WHERE m.company_id = ? AND m.item_id = ? AND m.warehouse_id = ?
              AND m.doc_date <= ? AND m.document_id <> ?
            """,
            (company_id, row["item_id"], row["warehouse_id"], doc["doc_date"], document_id),
        ).fetchone()[0]
        missing = row["quantity"] - max(available, 0)
        if missing > 0:
            result.append(_shortage(conn, company_id, row["item_id"], row["warehouse_id"], missing))
    return result


def _shortage(
    conn: Connection, company_id: int, item_id: int, warehouse_id: int, missing: int
) -> Shortage:
    last = conn.execute(
        """
        SELECT l.amount, l.quantity, l.offset_account_id, l.offset_sc1, l.offset_sc2,
               l.offset_sc3
        FROM inventory_lines l
        JOIN inventory_documents d
          ON d.company_id = l.company_id AND d.id = l.document_id
         AND d.status = 'posted' AND d.doc_type = 'receipt'
        WHERE l.company_id = ? AND l.item_id = ? AND l.quantity > 0
        ORDER BY d.doc_date DESC, d.id DESC LIMIT 1
        """,
        (company_id, item_id),
    ).fetchone()
    if last is None:
        return Shortage(item_id, warehouse_id, missing, None, None, (None, None, None))
    return Shortage(
        item_id,
        warehouse_id,
        missing,
        unit_price(last["amount"], last["quantity"]),
        last["offset_account_id"],
        (last["offset_sc1"], last["offset_sc2"], last["offset_sc3"]),
    )
