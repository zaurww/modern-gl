"""SQLite connection, explicit transactions and versioned migrations.

The only module that knows the database engine (D77): the rest of the code takes the
connection, row and error types from here, so moving to PostgreSQL changes this package,
not the queries' callers."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from modern_gl.domain.errors import LedgerError, ReadOnlyError
from modern_gl.i18n import fold, tr

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# The mark of a company file in the SQLite header ('MGL1', set by migration 0046); 0 is an
# empty or an older file of ours, anything else is another program's database.
APPLICATION_ID = int.from_bytes(b"MGL1", "big")
BUSY_TIMEOUT = 5.0  # seconds a connection waits for another program's lock on the file

# A row is read both by name (row["code"]) and by position (row[0]) and has .keys()
Connection = sqlite3.Connection
Row = sqlite3.Row
Error = sqlite3.Error
DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError


class NewerFileError(LedgerError):
    """The file was updated by a newer program: this one does not know its schema and
    leaves it untouched (D148)."""


class BusyError(LedgerError):
    """Another program holds the file's write lock longer than BUSY_TIMEOUT."""


@contextmanager
def _busy_is_an_error_for_the_user() -> Generator[None]:
    try:
        yield
    except sqlite3.OperationalError as e:
        if "locked" not in str(e) and "busy" not in str(e):
            raise
        raise BusyError(
            tr("Файл компании занят другой программой — закройте её и повторите")
        ) from e


class _Connection(sqlite3.Connection):
    """A company's connection that knows what goes with it: a lock file beside the file
    is released when it is closed (`when_closed`)."""

    def close(self) -> None:
        try:
            super().close()
        finally:
            for then in self.__dict__.pop("closed_then", []):
                then()


def when_closed(conn: sqlite3.Connection, then: Callable[[], None]) -> None:
    """Run `then` once the connection (made by `connect`) is closed."""
    conn.__dict__.setdefault("closed_then", []).append(then)


def journal_mode(path: str | Path) -> str:
    """WAL keeps its shared memory beside the file, and that is not shared on a network
    or cloud folder: there the file has the classic journal (D169)."""
    from modern_gl.infrastructure.company_file import is_network_path  # it imports this

    if str(path) in ("", ":memory:"):
        return "WAL"
    return "DELETE" if is_network_path(path) else "WAL"


def connect(path: str | Path, timeout: float = BUSY_TIMEOUT) -> sqlite3.Connection:
    """Open a ledger database and bring its schema up to date. A file another program
    keeps locked for longer than `timeout` is a BusyError, with a message for the user."""
    # isolation_level=None: no implicit transactions, we open them explicitly.
    conn = sqlite3.connect(path, isolation_level=None, timeout=timeout, factory=_Connection)
    conn.row_factory = sqlite3.Row
    _add_functions(conn)
    try:
        with _busy_is_an_error_for_the_user():
            _check_application_id(conn)  # before anything touches another program's file
            _check_not_newer(conn, path)  # before a migration writes to it
            conn.execute("PRAGMA foreign_keys = ON")
            migrate(conn)
            # after the migrations: one that fails leaves the file's header as it was
            conn.execute(f"PRAGMA journal_mode = {journal_mode(path)}")
            conn.execute("PRAGMA synchronous = FULL")  # accounting data: durability over speed
    except BaseException:
        conn.close()
        raise
    return conn


def _fold(text: str | None) -> str | None:
    return None if text is None else fold(text)


def _add_functions(conn: sqlite3.Connection) -> None:
    """`fold(text)` in SQL: the search form of `i18n.fold` (case, and İ/ı/ş/ə… = i/s/e…),
    so a list is searched in its query, not in the rows it read. On PostgreSQL the same
    function goes into the schema."""
    conn.create_function("fold", 1, _fold, deterministic=True)


def _check_application_id(conn: sqlite3.Connection) -> None:
    """Another program's database is refused before a migration touches it. 0 is what
    any program leaves by default, so it passes only for a new (empty) file or a file of
    ours written before 0046 — one with the companies table."""
    found = conn.execute("PRAGMA application_id").fetchone()[0]
    if found == APPLICATION_ID:
        return
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if found != 0 or (tables and ("companies",) not in [tuple(t) for t in tables]):
        raise sqlite3.DatabaseError(tr("это не файл компании Modern GL"))


def _check_not_newer(conn: sqlite3.Connection, path: str | Path) -> None:
    """An older program never writes to a newer file: it would leave out what the newer
    one keeps (new columns, new rules) and the file would no longer be true."""
    found, known = schema_version(conn), latest_version()
    if found > known:
        raise NewerFileError(
            tr(
                "Файл «{file}» обновлён более новой версией Modern GL (схема {found}, эта "
                "программа знает до {known}). Обновите программу — файл не изменён",
                file=Path(path).name,
                found=found,
                known=known,
            )
        )


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
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    _add_functions(conn)
    return conn


def open_snapshot(path: str | Path) -> sqlite3.Connection:
    """A company file for viewing only (D80): a copy in memory, brought up to the current
    schema there, that refuses every write. The file is only read — no lock is kept, no
    migration, no backup — so it may be open by its owner meanwhile. A damaged file raises
    sqlite3.DatabaseError."""
    from modern_gl.infrastructure.company_file import lock_path  # it imports this

    path = Path(path)
    # open by its owner (a -wal; on a network folder, without WAL, its lock): read under
    # the engine's locks; otherwise as an unchanging file, which leaves no -wal/-shm
    # beside it and works on a read-only share
    in_use = path.with_name(path.name + "-wal").exists()
    in_use = in_use or (lock_path(path).exists() and not _in_wal_mode(path))
    mode = "mode=ro" if in_use else "immutable=1"
    source = sqlite3.connect(f"file:{path.as_posix()}?{mode}", uri=True)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    _add_functions(conn)
    try:
        source.backup(conn)  # consistent even while the owner is writing
        found = [r[0] for r in conn.execute("PRAGMA quick_check(5)")]
        if found != ["ok"]:
            raise sqlite3.DatabaseError("; ".join(found))
        conn.row_factory = sqlite3.Row
        _check_application_id(conn)
        _check_not_newer(conn, path)
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    finally:
        source.close()
    conn.execute("PRAGMA query_only = ON")
    return conn


def scratch_copy(conn: sqlite3.Connection) -> sqlite3.Connection:
    """The open company copied into memory to try things on — the check of the books
    (D175) builds the modules' postings again there: writable even when the original is
    a snapshot (D80); the original is only read and keeps no lock."""
    copy = sqlite3.connect(":memory:", isolation_level=None, factory=_Connection)
    _add_functions(copy)
    try:
        conn.backup(copy)
        copy.row_factory = sqlite3.Row
        copy.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        copy.close()
        raise
    return copy


def file_problems(conn: sqlite3.Connection) -> list[str]:
    """What the engine finds wrong in the open file: damaged pages or indexes
    (integrity_check) and references to rows that are gone (foreign_key_check); empty
    when it is intact."""
    found = [r[0] for r in conn.execute("PRAGMA integrity_check(20)")]
    problems = [] if found == ["ok"] else found
    problems += [f"{r[0]} #{r[1]} → {r[2]}" for r in conn.execute("PRAGMA foreign_key_check")]
    return problems


def _in_wal_mode(path: Path) -> bool:
    """The file's header says WAL (its write version, byte 18, is 2)."""
    try:
        with path.open("rb") as f:
            return f.read(20)[18:19] == b"\x02"
    except OSError:
        return False


def is_read_only(conn: sqlite3.Connection) -> bool:
    """The company is open for viewing only (a snapshot, D80): every write is refused."""
    return bool(conn.execute("PRAGMA query_only").fetchone()[0])


_SAVEPOINTS = count(1)  # names of nested blocks: unique, so an inner one never hides an outer


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[None]:
    """Run the block atomically. Inside an open transaction the block is a savepoint of
    its own (D160): its failure undoes the block only, the outer transaction goes on —
    a loop that keeps the documents that posted and reports the ones that did not.
    A company open for viewing refuses at once, with a message for the user."""
    if conn.in_transaction:
        with _savepoint(conn, undo=False):
            yield
        return
    if is_read_only(conn):
        raise ReadOnlyError(tr("Компания открыта только для просмотра — изменения не сохраняются"))
    with _busy_is_an_error_for_the_user():
        conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    try:
        with _busy_is_an_error_for_the_user():
            conn.execute("COMMIT")
    except BaseException:
        # a refused COMMIT leaves the transaction open: the next transaction() would
        # join it as a savepoint and never be saved
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


@contextmanager
def dry_run(conn: sqlite3.Connection) -> Generator[None]:
    """Run the block and undo it whatever happens: a preview that is the real thing
    rolled back, so the two cannot differ. Joins an open transaction like `transaction`."""
    with transaction(conn), _savepoint(conn, undo=True):
        yield


@contextmanager
def _savepoint(conn: sqlite3.Connection, undo: bool) -> Generator[None]:
    name = f"sp_{next(_SAVEPOINTS)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    if undo:
        conn.execute(f"ROLLBACK TO {name}")
    conn.execute(f"RELEASE {name}")


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
    """The tables of the schema, without SQLite's own."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return [name for (name,) in rows.fetchall()]


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """The columns of a table (`table` — a name from the schema, not from the user)."""
    return {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def foreign_key_columns(conn: sqlite3.Connection, table: str) -> list[ForeignKeyColumn]:
    """What each column of the table refers to (`table` — a name from the schema)."""
    return [
        ForeignKeyColumn(k["from"], k["table"], k["to"], k["on_delete"])
        for k in conn.execute(f'PRAGMA foreign_key_list("{table}")')
    ]


def schema_version(conn: sqlite3.Connection) -> int:
    """The number of the last migration the file has (`user_version`)."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def latest_version() -> int:
    """The schema version this program brings files up to."""
    return max(int(p.name.split("_", 1)[0]) for p in MIGRATIONS_DIR.glob("*.sql"))


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations, all in one transaction: the file is either brought fully
    up to date or left exactly as the older program wrote it, which can still open it.
    Foreign keys are off meanwhile, so a migration may rebuild a referenced table (the
    SQLite way to change a column); dangling references are checked after each one."""
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
        conn.execute("BEGIN IMMEDIATE")
        try:
            for version, path in pending:
                _apply(conn, version, path)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _apply(conn: sqlite3.Connection, version: int, path: Path) -> None:
    """One migration inside the update's transaction (executescript would commit it:
    statements run one by one)."""
    script = f"{path.read_text(encoding='utf-8')}\nPRAGMA user_version = {version};"
    for statement in _statements(script):
        conn.execute(statement)
    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise sqlite3.IntegrityError(f"{path.name}: broken references {[tuple(r) for r in broken]}")


def _statements(script: str) -> Iterator[str]:
    """The statements of a script, in order. A semicolon ends a statement only where
    SQLite's own tokenizer says so: not inside a string, a comment or a trigger's body."""
    pending = ""
    for piece in script.split(";")[:-1]:
        pending += piece + ";"
        if sqlite3.complete_statement(pending):
            if not _only_comments(pending.replace(";", "")):
                yield pending
            pending = ""
    rest = pending + script.rsplit(";", 1)[-1]
    if not _only_comments(rest):
        raise sqlite3.OperationalError(f"incomplete statement: {rest.strip()[:80]}")


def _only_comments(text: str) -> bool:
    return all(not line.strip() or line.strip().startswith("--") for line in text.splitlines())
