"""Since when the company is a payer of ƏDV (D-new1): before that day no ƏDV is owed on
its sales nor credited on its purchases. A company set no day is a payer all along."""

from __future__ import annotations

from modern_gl.infrastructure.db import Connection


def payer_from(conn: Connection, company_id: int) -> str:
    """The first day of ƏDV (ISO); "" — a payer all along."""
    row = conn.execute("SELECT vat_payer_from FROM companies WHERE id = ?", (company_id,))
    return row.fetchone()[0] or ""
