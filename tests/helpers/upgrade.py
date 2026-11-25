"""Old and newer company files for the tests of updating (moved from test_schema_upgrade.py:
other test modules use them too)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from modern_gl.infrastructure import db
from modern_gl.infrastructure.db import close, connect, latest_version


def migrations_up_to(folder: Path, version: int, extra: str = "") -> Path:
    """A copy of the migrations up to `version`, with one more (`extra` SQL) after them."""
    folder.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= version:
            shutil.copy(path, folder / path.name)
    if extra:
        (folder / f"{version + 1:04d}_extra.sql").write_text(extra, encoding="utf-8")
    return folder


def old_file(path: Path, version: int, monkeypatch) -> Path:
    """A company file as a program of schema `version` left it, with one company."""
    full = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", migrations_up_to(path.parent / "old", version))
    conn = connect(path)
    conn.execute("INSERT INTO companies (name, created_at) VALUES ('Old', '2026-01-01')")
    close(conn)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", full)
    return path


def newer_file(path: Path) -> Path:
    """A company file a newer program has updated: its schema is one ahead of ours."""
    conn = connect(path)
    conn.execute("INSERT INTO companies (name, created_at) VALUES ('New', '2026-01-01')")
    conn.execute(f"PRAGMA user_version = {latest_version() + 1}")
    close(conn)
    return path


def version_of(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
