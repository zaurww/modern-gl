"""Shared from test_backup.py (moved here: other test modules use it too)."""

from __future__ import annotations

import sqlite3

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace


def company(ws: Workspace, name: str = "Firma"):
    path = ws.create(name, chart=None)
    conn, cid = ws.open(path)
    ledger = Ledger(conn)
    a = ledger.add_account(cid, "50", "Касса", account_class="asset")
    b = ledger.add_account(cid, "80", "Капитал", account_class="equity")
    return path, conn, ledger, cid, (a, b)


def documents(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()
