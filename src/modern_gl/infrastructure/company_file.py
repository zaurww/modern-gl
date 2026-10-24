"""One company file as a file: what the engine alone reads or does to it, before or beside
the schema — the name inside, the schema version, a consistent copy, one company kept
out of a shared file of the old kind (D18). The folder of such files, their creation and
copies are `application/workspace.py`."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from modern_gl.infrastructure.db import Connection, DatabaseError, connect


def read_only(path: Path) -> Connection:
    """The file as it is: not migrated, not locked."""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def company_name(path: Path) -> str:
    """Read the company name without migrating or locking the file."""
    conn = read_only(path)
    try:
        row = conn.execute("SELECT name FROM companies ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        raise DatabaseError("no company in file")
    return row[0]


def companies_in(path: Path) -> list[tuple[int, str]]:
    """(id, name) of every company in the file, oldest first: a shared file of the old
    kind holds several."""
    conn = read_only(path)
    try:
        return [tuple(r) for r in conn.execute("SELECT id, name FROM companies ORDER BY id")]
    finally:
        conn.close()


def open_company(path: Path) -> tuple[Connection, int]:
    """Open (and migrate) a company file; returns the connection and the company id."""
    conn = connect(path)
    return conn, first_company(conn, path)


def first_company(conn: Connection, path: Path) -> int:
    row = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
    if row is None:
        conn.close()
        raise DatabaseError(f"{path.name}: no company in file")
    return row["id"]


def file_version(path: Path) -> int:
    """The schema version written in the file, without migrating it."""
    conn = read_only(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def sidecars(path: Path) -> tuple[Path, Path]:
    """The -wal and -shm files the engine keeps beside an open file."""
    return path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")


def copy_file(source: Path, target: Path) -> None:
    """A consistent copy of the database file, even of one in use."""
    src = read_only(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def make_self_contained(conn: Connection) -> None:
    """One file and nothing beside it: how a new company file is handed over (D18)."""
    conn.execute("PRAGMA journal_mode = DELETE")


def keep_only(path: Path, company_id: int) -> None:
    """Delete every other company's rows from every table that has company_id. The
    immutability triggers would refuse to delete posted documents, so they are lifted for
    this copy only and put back; references left dangling stop it."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
        triggers = triggers.fetchall()
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if r[0] != "companies" and not r[0].startswith("sqlite_")
        ]
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        for trigger, _ in triggers:
            conn.execute(f'DROP TRIGGER "{trigger}"')
        for table in tables:
            columns = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            if "company_id" in columns:
                conn.execute(f'DELETE FROM "{table}" WHERE company_id IS NOT ?', (company_id,))
        conn.execute("DELETE FROM companies WHERE id != ?", (company_id,))
        for _, sql in triggers:
            conn.execute(sql)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            conn.execute("ROLLBACK")
            raise sqlite3.IntegrityError(
                f"{path.name}: broken references {[tuple(r) for r in broken][:5]}"
            )
        conn.execute("COMMIT")
        conn.execute("VACUUM")
    finally:
        conn.close()
