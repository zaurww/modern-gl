"""Shared from test_workspace.py (moved here: other test modules use it too)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from modern_gl.infrastructure.db import MIGRATIONS_DIR


def file_at_version(path: Path, version: int, companies: list[str]) -> None:
    """A shared file as an older program left it: the migrations up to `version`."""
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(migration.name.split("_", 1)[0])
        if number > version:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    for name in companies:
        old.execute("INSERT INTO companies (name, created_at) VALUES (?, 'now')", (name,))
    old.close()
