"""The warehouse documents: the list, and the one that made a GL document."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class InventoryDocumentSummary:
    id: int
    number: int
    doc_date: str
    doc_type: str
    memo: str
    status: str
    gl_document_id: int | None
    cost_type_name: str | None
    amount: int


# a purchase or sale of services only does not touch the warehouse
ON_WAREHOUSE = """(d.doc_type NOT IN ('receipt', 'sale') OR EXISTS (
    SELECT 1 FROM inventory_lines g
    WHERE g.document_id = d.id AND g.item_id IS NOT NULL
))"""


def inventory_document_kinds(conn: Connection, company_id: int) -> list[str]:
    """The kinds of the documents `list_inventory_documents` can show: the filter's list."""
    rows = conn.execute(
        f"""
        SELECT DISTINCT d.doc_type FROM inventory_documents d
        WHERE d.company_id = ? AND {ON_WAREHOUSE}
        ORDER BY d.doc_type
        """,
        (company_id,),
    )
    return [r["doc_type"] for r in rows]


def list_inventory_documents(
    conn: Connection, company_id: int, limit: int | None = 100, doc_type: str | None = None
) -> list[InventoryDocumentSummary]:
    """The latest `limit` (None: all) inventory documents with their total amount, of one
    kind if asked, listed oldest first. Purchases and sales without goods are left to
    «Покупки» and «Продажи»."""
    kind = "AND d.doc_type = ?" if doc_type is not None else ""
    latest = "LIMIT ?" if limit is not None else ""
    rows = conn.execute(
        f"""
        SELECT d.id, d.number, d.doc_date, d.doc_type, d.memo, d.status,
               d.gl_document_id,
               COALESCE(ct.name, (
                   SELECT string_agg(t.name, ', ') FROM landed_cost_charges c
                   JOIN landed_cost_types t ON t.id = c.cost_type_id
                   WHERE c.document_id = d.id
               )) AS cost_type_name,
               COALESCE(SUM(l.amount), 0) AS amount
        FROM inventory_documents d
        LEFT JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        LEFT JOIN landed_cost_types ct
          ON ct.company_id = d.company_id AND ct.id = d.landed_cost_type_id
        WHERE d.company_id = ? {kind} AND {ON_WAREHOUSE}
        GROUP BY d.id
        ORDER BY d.doc_date DESC, d.id DESC
        {latest}
        """,
        (
            company_id,
            *([doc_type] if doc_type is not None else []),
            *([limit] if limit is not None else []),
        ),
    )
    return [InventoryDocumentSummary(**dict(r)) for r in reversed(rows.fetchall())]
