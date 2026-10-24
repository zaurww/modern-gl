"""SQLite connection, explicit transactions and versioned migrations.

The only module that knows the database engine (D77): the rest of the code takes the
connection, row and error types from here, so moving to PostgreSQL changes this package,
not the queries' callers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from modern_gl.domain.errors import ReadOnlyError
from modern_gl.i18n import tr

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# The mark of a company file in the SQLite header ('MGL1', set by migration 0046); 0 is an
# empty or an older file of ours, anything else is another program's database.
APPLICATION_ID = int.from_bytes(b"MGL1", "big")

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
    try:
        _check_application_id(conn)  # before anything touches another program's file
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")  # accounting data: durability over speed
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _check_application_id(conn: sqlite3.Connection) -> None:
    found = conn.execute("PRAGMA application_id").fetchone()[0]
    if found not in (0, APPLICATION_ID):
        raise sqlite3.DatabaseError(tr("это не файл компании Modern GL"))


def close(conn: sqlite3.Connection) -> None:
    """Close a company's connection. A writable file first refreshes the statistics the
    query planner chooses indexes by (PRAGMA optimize: cheap, only what the session's
    queries showed to be stale); a snapshot (D80) is closed as it is."""
    if not is_read_only(conn) and not conn.in_transaction:
        conn.execute("PRAGMA optimize")
    conn.close()


def connect_reader(path: str | Path) -> sqlite3.Connection:
    """A second connection to an open company's file, for reading in a worker thread
    (desktop.background): read-only, no migration; WAL lets it read beside the writer."""
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_snapshot(path: str | Path) -> sqlite3.Connection:
    """A company file for viewing only (D80): a copy in memory, brought up to the current
    schema there, that refuses every write. The file is only read — no lock is kept, no
    migration, no backup — so it may be open by its owner meanwhile. A damaged file raises
    sqlite3.DatabaseError."""
    path = Path(path)
    # open by its owner (there is a -wal): read through the owner's WAL; otherwise as an
    # unchanging file, which leaves no -wal/-shm beside it and works on a read-only share
    in_use = path.with_name(path.name + "-wal").exists()
    mode = "mode=ro" if in_use else "immutable=1"
    source = sqlite3.connect(f"file:{path.as_posix()}?{mode}", uri=True)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        source.backup(conn)  # consistent even while the owner is writing
        found = [r[0] for r in conn.execute("PRAGMA quick_check(5)")]
        if found != ["ok"]:
            raise sqlite3.DatabaseError("; ".join(found))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    finally:
        source.close()
    conn.execute("PRAGMA query_only = ON")
    return conn


def is_read_only(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("PRAGMA query_only").fetchone()[0])


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run the block atomically. Joins the outer transaction if one is already open.
    A company open for viewing refuses at once, with a message for the user."""
    if conn.in_transaction:
        yield
        return
    if is_read_only(conn):
        raise ReadOnlyError(tr("Компания открыта только для просмотра — изменения не сохраняются"))
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def insert(conn: sqlite3.Connection, sql: str, params: Sequence[object] = ()) -> int:
    """Run an INSERT and return the id of the new row."""
    row_id = conn.execute(sql, params).lastrowid
    if row_id is None:  # only when the statement inserted nothing
        raise RuntimeError(f"no row inserted: {sql}")
    return row_id


@dataclass(frozen=True)
class ForeignKeyColumn:
    """One column of a foreign key: `column` refers to `table`.`to`."""

    column: str
    table: str
    to: str
    on_delete: str  # "CASCADE", "NO ACTION", ...


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return [name for (name,) in rows.fetchall()]


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def foreign_key_columns(conn: sqlite3.Connection, table: str) -> list[ForeignKeyColumn]:
    return [
        ForeignKeyColumn(k["from"], k["table"], k["to"], k["on_delete"])
        for k in conn.execute(f'PRAGMA foreign_key_list("{table}")')
    ]


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
