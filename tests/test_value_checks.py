"""Values the file refuses (migration 0057, D155): a day that is not in the calendar, a
time that is not a time, a flag that is neither 0 nor 1, an account whose class is not its
type's. Written straight to the file — as a mistake of the code, an import or a tool would."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from modern_gl.application.common import local_day
from modern_gl.application.ledger import Ledger
from modern_gl.demo_data import create_demo_company
from modern_gl.domain.accounts import TYPE_CLASS
from modern_gl.infrastructure.db import close, connect, table_names

DATE_COLUMNS = re.compile(r"(_date|^date_from|^date_to|^closed_through)$")
TIME_COLUMNS = re.compile(r"(_at|^at|^first_seen|^last_seen)$")
FLAG_COLUMNS = re.compile(r"^(active|is_\w+|contra|two_sided|closed|pays_vat|nonresident)$")


@pytest.fixture(scope="module")
def demo() -> Iterator[sqlite3.Connection]:
    conn = connect(":memory:")
    create_demo_company(Ledger(conn))
    yield conn
    close(conn)


@pytest.fixture
def db(demo) -> Iterator[sqlite3.Connection]:
    demo.execute("BEGIN")
    yield demo
    demo.execute("ROLLBACK")


def refused(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> str:
    with pytest.raises(sqlite3.IntegrityError) as e:
        conn.execute(sql, params)
    return str(e.value)


def guarded(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """A CHECK in the table's own SQL, or a trigger of the table that names the column."""
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    if re.search(rf"\b{column}\b[^,]*CHECK", sql):
        return True
    triggers = " ".join(
        r[0]
        for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?", (table,)
        )
    )
    return f"NEW.{column}" in triggers


@pytest.mark.parametrize(
    "kind, pattern",
    [("даты", DATE_COLUMNS), ("время", TIME_COLUMNS), ("флаг", FLAG_COLUMNS)],
)
def test_every_column_of_its_kind_is_checked(kind, pattern):
    """A new table checks its dates, times and flags too (in its CREATE or a trigger)."""
    conn = connect(":memory:")
    missing = [
        f"{t}.{r[1]}"
        for t in table_names(conn)
        for r in conn.execute(f"PRAGMA table_info({t})").fetchall()
        if pattern.search(r[1])
        and not (kind == "даты" and t == "audit_events")
        and not guarded(conn, t, r[1])
    ]
    close(conn)
    assert not missing, f"{kind} без проверки: {missing}"


# ---- days and times ---------------------------------------------------------------------


@pytest.mark.parametrize("day", ["2026-02-30", "2026-13-01", "2026-04-31"])
def test_a_day_not_in_the_calendar_is_refused(db, day):
    sql = "UPDATE documents SET doc_date = ? WHERE id = (SELECT MIN(id) FROM documents)"
    assert "not a day" in refused(db, sql, (day,))


def test_a_real_day_passes(db):
    db.execute("UPDATE documents SET doc_date = '2028-02-29' WHERE status = 'draft'")


def test_a_time_that_is_not_a_time_is_refused(db):
    sql = "UPDATE documents SET created_at = 'вчера' WHERE id = (SELECT MIN(id) FROM documents)"
    assert "not a time" in refused(db, sql)


def test_a_day_is_the_users_day():
    """Stored times are UTC: a mark made at 02:30 in Baku on 1 April is 31 March in UTC."""
    baku = timezone(timedelta(hours=4))
    stamp = datetime(2026, 3, 31, 22, 30, tzinfo=UTC).isoformat()
    assert local_day(stamp, baku) == date(2026, 4, 1)
    assert local_day("2026-03-31T22:30:00", baku) == date(2026, 3, 31)  # no zone: as written


# ---- flags and codes --------------------------------------------------------------------


@pytest.mark.parametrize(
    "table, column, value",
    [
        ("accounts", "active", 2),
        ("accounts", "is_group", 5),
        ("accounts", "contra", -1),
        ("accounts", "two_sided", 3),
        ("accounts", "currency", 3),
        ("currencies", "active", 2),
        ("subconto_values", "active", 2),
    ],
)
def test_a_flag_is_zero_or_one(db, table, column, value):
    sql = f"UPDATE {table} SET {column} = ? WHERE id = (SELECT MIN(id) FROM {table})"
    assert "flag" in refused(db, sql, (value,))


def test_the_currency_mode_has_three_values(db):
    db.execute("UPDATE accounts SET currency = 2 WHERE id = (SELECT MIN(id) FROM accounts)")


def test_the_base_currency_is_a_code(db):
    sql = "UPDATE companies SET base_currency = 'manat'"
    assert "currency code" in refused(db, sql)


# ---- an account's class is its type's ---------------------------------------------------


def test_an_account_of_a_type_keeps_its_class(db):
    typed = db.execute(
        "SELECT id, account_type FROM accounts WHERE account_type IS NOT NULL LIMIT 1"
    ).fetchone()
    other = next(c for c in ("asset", "liability", "equity") if c != TYPE_CLASS[typed[1]])
    sql = "UPDATE accounts SET account_class = ? WHERE id = ?"
    assert "type of another class" in refused(db, sql, (other, typed[0]))


def test_every_type_is_known_to_the_file(demo):
    """A new account type is added to the trigger of the file in its migration too."""
    sql = demo.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'accounts_type_class_insert'"
    ).fetchone()[0]
    missing = [t for t, cls in TYPE_CLASS.items() if f"WHEN '{t}' THEN '{cls}'" not in sql]
    assert not missing, missing
