"""Purchase and sale drafts posted in bulk (D73): the invoices of one supplier come every
month and are booked the same way, so the user filters them and posts them at once.

A purchase line without an item and without an account (a service, fuel) gets the account
and subconto of the last posted purchase of the same name — from this supplier, else from
anyone — else of the supplier's last expense line (`queries.remembered_expense`, D76).
The drafts post in date order, so one posted earlier in the batch teaches the later ones.
Each draft is its own transaction: one that cannot post stays a draft and the reason is
reported."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.inventory import Inventory
from modern_gl.application.queries import remembered_expense
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import Connection, transaction


@dataclass
class BulkPosting:
    posted: list[int] = field(default_factory=list)  # document ids
    filled: int = 0  # purchase lines given an account like the last time
    failed: list[tuple[int, str]] = field(default_factory=list)  # (number, why)


def post_drafts(inventory: Inventory, company_id: int, document_ids: Sequence[int]) -> BulkPosting:
    """Post the purchase and sale drafts among `document_ids`, earliest first."""
    conn = inventory.conn
    result = BulkPosting()
    if not document_ids:
        return result
    marks = ", ".join("?" * len(document_ids))
    drafts = conn.execute(
        f"SELECT id, number, doc_type FROM inventory_documents "
        f"WHERE company_id = ? AND id IN ({marks}) AND status = 'draft' "
        f"AND doc_type IN ('receipt', 'sale') ORDER BY doc_date, number",
        (company_id, *document_ids),
    ).fetchall()
    for doc in drafts:
        try:
            with transaction(conn):
                filled = 0
                if doc["doc_type"] == "receipt":
                    filled = _fill_like_last_time(inventory, company_id, doc["id"])
                inventory.post_document(company_id, doc["id"])
        except LedgerError as exc:
            result.failed.append((doc["number"], str(exc)))
            continue
        result.posted.append(doc["id"])
        result.filled += filled
    return result


def _fill_like_last_time(inventory: Inventory, company_id: int, document_id: int) -> int:
    conn = inventory.conn
    open_lines = conn.execute(
        "SELECT id, memo FROM inventory_lines WHERE company_id = ? AND document_id = ? "
        "AND item_id IS NULL AND cost_account_id IS NULL ORDER BY line_no",
        (company_id, document_id),
    ).fetchall()
    if not open_lines:
        return 0
    supplier = _counterparty(conn, company_id, document_id)
    filled = 0
    for line in open_lines:
        remembered = remembered_expense(conn, company_id, line["memo"] or "", supplier)
        if remembered is None:
            continue
        inventory.fill_expense_account(company_id, document_id, line["id"], *remembered)
        filled += 1
    return filled


def _counterparty(conn: Connection, company_id: int, document_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT v.id FROM inventory_lines x
        JOIN subconto_values v
          ON v.company_id = x.company_id AND v.id IN (x.offset_sc1, x.offset_sc2, x.offset_sc3)
        JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'counterparty'
        WHERE x.company_id = ? AND x.document_id = ?
        ORDER BY x.line_no LIMIT 1
        """,
        (company_id, document_id),
    ).fetchone()
    return row["id"] if row else None
