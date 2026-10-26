"""The file keeps the rules of the code (migration 0053, D-new2): money is never a fraction,
the closed period is not changed, and the rows a module built a closed document from stay.
Written straight to the file — as a mistake of the code, an import or a tool would."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import create_year_demo
from modern_gl.infrastructure.db import close, connect, table_names


@pytest.fixture(scope="module")
def year() -> Iterator[tuple[sqlite3.Connection, int]]:
    """The year demo: closed through 30.06.2026, every module in both halves."""
    conn = connect(":memory:")
    company_id = create_year_demo(Ledger(conn))
    yield conn, company_id
    close(conn)


@pytest.fixture
def db(year) -> Iterator[sqlite3.Connection]:
    """The year demo inside a transaction that is undone after the test."""
    conn, _ = year
    conn.execute("BEGIN")
    yield conn
    conn.execute("ROLLBACK")


def refused(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> str:
    with pytest.raises(sqlite3.IntegrityError) as e:
        conn.execute(sql, params)
    return str(e.value)


def one(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


# ---- 1. integers ------------------------------------------------------------------------


def test_every_integer_column_of_every_table_is_guarded():
    """A new table gets its `<table>_integers_insert/update` triggers in its migration."""
    conn = connect(":memory:")
    missing = []
    for table in table_names(conn):
        triggers = " ".join(
            r[0]
            for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ? "
                "AND name LIKE ?",
                (table, f"{table}_integers_%"),
            )
        )
        for r in conn.execute(f"PRAGMA table_info({table})"):
            integer = r[2] == "INTEGER" and not (r[5] and r[1] == "id")
            if integer and f"typeof(NEW.{r[1]})" not in triggers:
                missing.append(f"{table}.{r[1]}")
    close(conn)
    assert not missing, f"INTEGER без проверки typeof (триггер <таблица>_integers_*): {missing}"


@pytest.mark.parametrize("value", [12.5, "12,5", "abc", b"\x01"])
def test_money_is_never_a_fraction_or_text(db, value):
    draft = one(db, "SELECT MIN(id) FROM documents WHERE status = 'draft'")
    message = refused(db, "UPDATE postings SET amount = ? WHERE document_id = ?", (value, draft))
    assert "postings: not an integer" in message


def test_a_whole_number_written_as_text_is_stored_as_an_integer(db):
    draft = one(db, "SELECT MIN(id) FROM documents WHERE status = 'draft'")
    db.execute("UPDATE postings SET amount = '700' WHERE document_id = ?", (draft,))
    rows = db.execute(
        "SELECT DISTINCT amount, typeof(amount) FROM postings WHERE document_id = ?", (draft,)
    )
    assert [tuple(r) for r in rows] == [(700, "integer")]


def test_a_row_written_before_stays_editable(db):
    """Only a changed value is checked: a fraction left by an older program does not lock
    the rest of its row."""
    draft = one(db, "SELECT MIN(id) FROM documents WHERE status = 'draft'")
    line = one(db, f"SELECT MIN(id) FROM postings WHERE document_id = {draft}")
    db.execute("DROP TRIGGER postings_integers_update")  # as an older program wrote it
    db.execute("UPDATE postings SET amount = 12.5 WHERE id = ?", (line,))
    db.execute(
        "CREATE TRIGGER postings_integers_update BEFORE UPDATE ON postings "
        "WHEN NEW.amount IS NOT OLD.amount AND typeof(NEW.amount) NOT IN ('integer', 'null') "
        "BEGIN SELECT RAISE(ABORT, 'postings: not an integer'); END"
    )
    db.execute("UPDATE postings SET memo = 'fixed later' WHERE id = ?", (line,))


# ---- 2. the closed period ---------------------------------------------------------------


def test_the_demo_has_both_periods(year):
    conn, company_id = year
    assert one(conn, f"SELECT closed_through FROM companies WHERE id = {company_id}") == (
        "2026-06-30"
    )


def test_a_posted_document_of_the_closed_period_is_not_unposted(db):
    closed = one(
        db, "SELECT MIN(id) FROM documents WHERE status = 'posted' AND doc_date <= '2026-06-30'"
    )
    message = refused(db, "UPDATE documents SET status = 'draft' WHERE id = ?", (closed,))
    assert "period is closed" in message


def test_a_document_is_not_posted_into_the_closed_period(db):
    draft = one(db, "SELECT MIN(id) FROM documents WHERE status = 'draft'")
    # a draft may lie in the closed period, it is not posted there
    db.execute("UPDATE documents SET doc_date = '2026-03-01' WHERE id = ?", (draft,))
    sql = "UPDATE documents SET status = 'posted' WHERE id = ?"
    assert "period is closed" in refused(db, sql, (draft,))
    message = refused(
        db,
        "INSERT INTO documents (company_id, number, doc_date, memo, status, layer_id, "
        "created_at) SELECT company_id, 99999, '2026-03-01', '', 'posted', layer_id, "
        "created_at FROM documents WHERE id = ?",
        (draft,),
    )
    assert "period is closed" in message


def test_the_open_period_is_changed_as_before(db):
    open_doc = one(
        db, "SELECT MIN(id) FROM documents WHERE status = 'posted' AND doc_date > '2026-06-30'"
    )
    db.execute("UPDATE documents SET status = 'draft' WHERE id = ?", (open_doc,))
    db.execute("UPDATE documents SET status = 'posted' WHERE id = ?", (open_doc,))


def test_a_warehouse_document_of_the_closed_period_is_not_unposted(db):
    closed = one(
        db,
        "SELECT MIN(id) FROM inventory_documents "
        "WHERE status = 'posted' AND doc_date <= '2026-06-30'",
    )
    message = refused(db, "UPDATE inventory_documents SET status = 'draft' WHERE id = ?", (closed,))
    assert "period is closed" in message


# ---- 3. what a module built a closed document from --------------------------------------

CLOSED_BANK = (
    "SELECT MIN(o.id) FROM bank_operations o JOIN documents d ON d.id = o.document_id "
    "WHERE d.status = 'posted' AND d.doc_date <= '2026-06-30'"
)


def test_the_bank_operation_of_a_closed_document_stays(db):
    operation = one(db, CLOSED_BANK)
    sql = "UPDATE bank_operation_lines SET amount = amount + 1 WHERE operation_id = ?"
    assert "period is closed" in refused(db, sql, (operation,))
    sql = "DELETE FROM bank_operation_lines WHERE operation_id = ?"
    assert "period is closed" in refused(db, sql, (operation,))
    sql = "UPDATE bank_operations SET kind = kind || 'x' WHERE id = ?"
    assert "period is closed" in refused(db, sql, (operation,))


def test_the_reference_of_a_closed_bank_operation_may_be_written(db):
    """The statement line found later (ƏDV DH import) does not change the postings."""
    db.execute("UPDATE bank_operations SET reference = 'R-1' WHERE id = ?", (one(db, CLOSED_BANK),))


def test_the_conversion_of_a_closed_document_stays(db):
    conversion = one(
        db,
        "SELECT MIN(v.id) FROM currency_conversions v JOIN documents d ON d.id = v.document_id "
        "WHERE d.status = 'posted' AND d.doc_date <= '2026-06-30'",
    )
    sql = "UPDATE currency_conversions SET to_amount = to_amount + 1 WHERE id = ?"
    assert "period is closed" in refused(db, sql, (conversion,))
