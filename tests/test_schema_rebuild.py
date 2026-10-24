"""Migration 0047 rebuilds fourteen tables (docs/ENGINEERING.md 3.7: a data move is tested
on a file of the previous version): a company written by the program of schema 46 is
brought to the current schema with every row, id and column the same, and the file stays
whole."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import create_year_demo
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect, latest_version
from tests.test_workspace import file_at_version

REBUILT = 47
REBUILT_TABLES = (
    "companies", "subconto_kinds", "subconto_values", "postings", "inventory_documents",
    "inventory_lines", "landed_cost_charges", "stock_movements", "bank_statements",
    "bank_portal_loads", "bank_portal_reconciled", "eqaime_portal", "eqaime_portal_changes",
    "eqaime_reconciled",
)  # fmt: skip


def rows_by_table(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Every row of every table, by its id, columns as the schema names them."""
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    result = {}
    for table in names:
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        order = "id" if "id" in columns else ", ".join(columns)
        result[table] = [
            tuple(r)
            for r in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")
        ]
    return result


def company_of_version(path: Path, version: int) -> None:
    """The demo year written into a file of an older schema: the columns of 0046 and 0047
    are the same, so the program of today can fill a file of yesterday — once its accounts
    take the account types of today (0048: the same columns, a longer CHECK)."""
    file_at_version(path, version, [])
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    sql = (MIGRATIONS_DIR / "0048_ifrs_types.sql").read_text(encoding="utf-8")
    conn.executescript(sql[sql.index("CREATE TABLE") : sql.index("-- 09 and 77")])
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        create_year_demo(Ledger(conn))
        fill_the_empty_tables(conn)
    finally:
        conn.close()


def fill_the_empty_tables(conn: sqlite3.Connection) -> None:
    """The demo year leaves the bank statements, the portal loads and the portal changes
    empty: a row in each, so every copy of 0047 moves something."""
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    bank = conn.execute(
        "SELECT id FROM accounts WHERE company_id = ? AND account_type = 'bank'", (cid,)
    ).fetchone()["id"]
    period = (cid, bank, "2026-03-01", "2026-03-31")
    conn.execute(
        "INSERT INTO bank_statements (company_id, account_id, date_from, date_to, bank_closing)"
        " VALUES (?, ?, ?, ?, 12345)",
        period,
    )
    conn.execute(
        "INSERT INTO bank_portal_loads (company_id, account_id, date_from, date_to, loaded_at,"
        " operations) VALUES (?, ?, ?, ?, '2026-04-01 10:00', 7)",
        period,
    )
    conn.execute(
        "INSERT INTO bank_portal_reconciled (company_id, account_id, date_from, date_to,"
        " reconciled_at, portal_opening, portal_in, portal_out, books_opening, books_in,"
        " books_out) VALUES (?, ?, ?, ?, '2026-04-01 10:00', 100, 200, 300, 100, 200, 300)",
        period,
    )
    portal = conn.execute(
        "SELECT id, doc_date, status, party_tin, total, vat FROM eqaime_portal "
        "WHERE company_id = ? ORDER BY id LIMIT 1",
        (cid,),
    ).fetchone()
    conn.execute(
        "INSERT INTO eqaime_portal_changes (company_id, portal_id, seen_at, old_status,"
        " new_status, old_date, new_date, old_tin, new_tin, old_total, new_total, old_vat,"
        " new_vat) VALUES (?, ?, '2026-04-02 09:00', ?, 'CANCELLED', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            portal["id"],
            portal["status"],
            portal["doc_date"],
            portal["doc_date"],
            portal["party_tin"],
            portal["party_tin"],
            portal["total"],
            portal["total"] + 100,
            portal["vat"],
            portal["vat"] + 18,
        ),
    )


def test_rebuilt_tables_keep_every_row(tmp_path):
    path = tmp_path / "old.gl"
    company_of_version(path, REBUILT - 1)
    before_conn = sqlite3.connect(path)
    before = rows_by_table(before_conn)
    before_conn.close()
    assert all(before[t] for t in REBUILT_TABLES), "a rebuilt table has nothing to move"

    conn = connect(path)  # migrates
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        after = rows_by_table(conn)
    finally:
        conn.close()
    assert after == before


def test_company_scoped_references_replace_the_triggers():
    """Debt 4: the composite foreign keys of 0047 do what the triggers of 0008/0009/0027 did."""
    conn = connect(":memory:")
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert not {t for t in triggers if t.endswith(("_company_insert", "_company_update"))}
    composite = {
        (fk[3], fk[2])
        for table in ("postings", "subconto_values", "subconto_kinds", "inventory_documents")
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})")
        if fk[3] != "company_id"
    }
    assert {
        ("currency_id", "currencies"),
        ("owner_id", "subconto_values"),
        ("parent_id", "subconto_values"),
        ("owner_kind_id", "subconto_kinds"),
        ("accrual_document_id", "documents"),
    } <= composite
    conn.close()
