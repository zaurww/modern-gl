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
from tests.helpers.workspace import file_at_version

REBUILT = 47
REBUILT_TABLES = (
    "companies", "subconto_kinds", "subconto_values", "postings", "inventory_documents",
    "inventory_lines", "landed_cost_charges", "stock_movements", "bank_statements",
    "bank_portal_loads", "bank_portal_reconciled", "eqaime_portal", "eqaime_portal_changes",
    "eqaime_reconciled",
)  # fmt: skip
POSTED_TABLES = ("documents", "inventory_documents")  # the triggers guard their posted rows


def table_columns(conn: sqlite3.Connection) -> dict[str, list[str]]:
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in names}


def rows_by_table(
    conn: sqlite3.Connection, columns_of: dict[str, list[str]] | None = None
) -> dict[str, list[tuple]]:
    """Every row of every table, by its id — the columns the schema names, or `columns_of`
    (those of another schema, to compare across a migration that adds or drops one)."""
    result = {}
    for table, columns in (columns_of or table_columns(conn)).items():
        order = "id" if "id" in columns else ", ".join(columns)
        result[table] = [
            tuple(r)
            for r in conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}")
        ]
    return result


def plain(rows) -> list[tuple]:
    return [tuple(r) for r in rows]


def rows_by_table_projection(rows: list[tuple], columns: list[str], keep: list[str]) -> list[tuple]:
    """The rows with only the `keep` columns (a column dropped by a later migration)."""
    positions = [columns.index(c) for c in keep]
    return [tuple(r[i] for i in positions) for r in rows]


def company_of_version(path: Path, version: int) -> None:
    """The demo year as the program of yesterday would have left it: written by the program
    of today, then copied into a file of schema `version` column by column (0048's longer
    CHECK of account types is applied to the old file first). What later migrations moved
    goes back to where yesterday kept it: the month of a purchase's expense and its accrual
    document on the purchase (0050)."""
    file_at_version(path, version, [])
    today = connect(":memory:")
    create_year_demo(Ledger(today))
    fill_the_empty_tables(today)
    old = sqlite3.connect(path, isolation_level=None)
    old.row_factory = sqlite3.Row
    sql = (MIGRATIONS_DIR / "0048_ifrs_types.sql").read_text(encoding="utf-8")
    old.executescript(sql[sql.index("CREATE TABLE") : sql.index("-- 09 and 77")])
    try:
        # one transaction: in autocommit mode every row of the copy would be its own
        # commit with a sync of the file — minutes instead of seconds
        old.execute("BEGIN")
        copy_rows(today, old)
        old.executemany(
            "UPDATE inventory_documents SET expense_date = ?, accrual_document_id = ? WHERE id = ?",
            today.execute(
                "SELECT expense_date, gl_document_id, document_id FROM inventory_accruals"
            ).fetchall(),
        )
        post_again(today, old)
        old.execute("COMMIT")
    finally:
        old.close()
        today.close()


def copy_rows(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    """Every row of every table both schemas have, in the columns they share. Posted
    documents are written as drafts (their lines could not be added to a posted one):
    `post_again` once everything is in."""
    target_columns = table_columns(target)
    for table, columns in table_columns(source).items():
        shared = [c for c in columns if c in target_columns.get(table, ())]
        if not shared:
            continue
        rows = source.execute(f"SELECT {', '.join(shared)} FROM {table}").fetchall()
        if table in POSTED_TABLES:
            status = shared.index("status")
            rows = [tuple("draft" if i == status else v for i, v in enumerate(r)) for r in rows]
        target.executemany(
            f"INSERT INTO {table} ({', '.join(shared)}) VALUES ({', '.join('?' * len(shared))})",
            rows,
        )


def post_again(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    for table in POSTED_TABLES:
        target.executemany(
            f"UPDATE {table} SET status = ? WHERE id = ?",
            source.execute(f"SELECT status, id FROM {table}").fetchall(),
        )


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
    before_columns = table_columns(before_conn)
    before = rows_by_table(before_conn)
    moved = plain(
        before_conn.execute(
            "SELECT id, expense_date, accrual_document_id FROM inventory_documents "
            "WHERE accrual_document_id IS NOT NULL ORDER BY id"
        )
    )
    before_conn.close()
    assert all(before[t] for t in REBUILT_TABLES), "a rebuilt table has nothing to move"
    assert moved, "no purchase with an accrual to move (0050)"

    conn = connect(path)  # migrates
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version()
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        after_columns = table_columns(conn)
        shared = {
            t: [c for c in columns if c in after_columns.get(t, ())]
            for t, columns in before_columns.items()
        }
        after = rows_by_table(conn, {t: c for t, c in shared.items() if c})
        # 0050: the month and the accrual of a purchase moved to its lines and to
        # inventory_accruals, the same values
        assert (
            plain(
                conn.execute(
                    "SELECT document_id, expense_date, gl_document_id FROM inventory_accruals "
                    "ORDER BY document_id"
                )
            )
            == moved
        )
        for document_id, expense_date, _accrual in moved:
            months = conn.execute(
                "SELECT DISTINCT expense_date FROM inventory_lines "
                "WHERE document_id = ? AND item_id IS NULL",
                (document_id,),
            )
            assert plain(months) == [(expense_date,)]
        newer = {t for t in after_columns if t not in before_columns} - {"inventory_accruals"}
        assert all(not rows_by_table(conn, {t: after_columns[t]})[t] for t in newer)
    finally:
        conn.close()
    assert after == {
        t: rows_by_table_projection(rows, before_columns[t], shared[t])
        for t, rows in before.items()
        if shared[t]
    }


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
        ("gl_document_id", "documents"),
    } <= composite
    conn.close()
