"""Fees loaded before the bank's settings named their account (D62): found on the
other accounts, in the open period only — a closed period keeps what it has (D5)."""

from __future__ import annotations

from modern_gl.infrastructure.db import Connection


def fees_elsewhere(conn: Connection, company_id: int, fee_account: int) -> dict[int, list[int]]:
    """The account a fee line is on -> the bank operations (fees) with lines there, of
    the open period; the fee account itself left out."""
    rows = conn.execute(
        "SELECT DISTINCT l.account_id, o.id FROM bank_operations o "
        "JOIN documents d ON d.id = o.document_id "
        "JOIN bank_operation_lines l ON l.company_id = o.company_id AND l.operation_id = o.id "
        "JOIN companies c ON c.id = o.company_id "
        "WHERE o.company_id = ? AND o.kind = 'fee' AND l.account_id IS NOT NULL "
        "AND l.account_id <> ? "
        "AND (c.closed_through IS NULL OR d.doc_date > c.closed_through) "
        "ORDER BY l.account_id, o.id",
        (company_id, fee_account),
    ).fetchall()
    found: dict[int, list[int]] = {}
    for r in rows:
        found.setdefault(r["account_id"], []).append(r["id"])
    return found
