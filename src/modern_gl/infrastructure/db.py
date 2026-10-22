"""SQLite connection, explicit transactions and versioned migrations.

The only module that knows the database engine (D77): the rest of the code takes the
connection, row and error types from here, so moving to PostgreSQL changes this package,
not the queries' callers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# A row is read both by name (row["code"]) and by position (row[0]) and has .keys()
Connection = sqlite3.Connection
Row = sqlite3.Row
Error = sqlite3.Error
DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a ledger database and bring its schema up to date."""
    # isolation_level=None: no implicit transactions, we open them explicitly.
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")  # accounting data: durability over speed
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run the block atomically. Joins the outer transaction if one is already open."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def latest_version() -> int:
    """The schema version this program brings files up to."""
    return max(int(p.name.split("_", 1)[0]) for p in MIGRATIONS_DIR.glob("*.sql"))


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Foreign keys are off meanwhile, so a migration may
    rebuild a referenced table (the SQLite way to change a column); dangling
    references are checked before each migration commits."""
    current = schema_version(conn)
    pending = [
        (version, path)
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if (version := int(path.name.split("_", 1)[0])) > current
    ]
    if not pending:
        return
    conn.execute("PRAGMA foreign_keys = OFF")  # no effect inside a transaction
    try:
        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            try:
                conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};")
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise sqlite3.IntegrityError(
                        f"{path.name}: broken references {[tuple(r) for r in broken]}"
                    )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
