"""Updating a company file to a newer program (D-new): the update is all or nothing, an
older program refuses a newer file without touching it, a failed update is a message
with the copy made before it, and that copy outlives the usual rotation of backups."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from modern_gl.application.workspace import UpgradeError, Workspace
from modern_gl.infrastructure import backup, db
from modern_gl.infrastructure.db import NewerFileError, close, connect, latest_version


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


# ---- an older program and a newer file --------------------------------------------------


def test_an_older_program_refuses_a_newer_file_and_leaves_it_as_it_was(tmp_path):
    path = newer_file(tmp_path / "New.gl")
    before = path.read_bytes()
    with pytest.raises(NewerFileError, match="Обновите программу"):
        connect(path)
    with pytest.raises(NewerFileError):
        db.open_snapshot(path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["New.gl"]


def test_a_newer_file_is_neither_backed_up_nor_called_damaged(tmp_path):
    ws = Workspace(tmp_path / "data")
    path = newer_file(ws.folder / "New.gl")
    with pytest.raises(NewerFileError):
        ws.open(path)
    with pytest.raises(NewerFileError):
        ws.view(path)
    assert ws.backups(path) == []


def test_the_window_says_why_it_cannot_open_a_newer_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.desktop.main_window import MainWindow

    said: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda _w, _t, text: said.append(text))
    )
    ws = Workspace(tmp_path / "data")
    path = newer_file(ws.folder / "New.gl")
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.open_company(path)
    assert win.session is None
    assert len(said) == 1 and "Обновите программу" in said[0]


# ---- the update is all or nothing ---------------------------------------------------------


def test_a_failed_update_leaves_the_file_at_its_old_version(tmp_path, monkeypatch):
    """Two migrations are pending and the second fails: the first is undone too, so the
    file stays exactly the old program's file and that program still opens it."""
    path = old_file(tmp_path / "Old.gl", 50, monkeypatch)
    broken = migrations_up_to(tmp_path / "new", 51, extra="INSERT INTO no_such_table VALUES (1);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", broken)
    with pytest.raises(db.Error):
        connect(path)
    assert version_of(path) == 50
    check = sqlite3.connect(path)
    columns = {r[1] for r in check.execute("PRAGMA table_info(eqaime_reconciled)")}
    check.close()
    assert "book_digest" not in columns  # 0051 undone with the broken one after it


def test_a_failed_update_is_a_message_naming_the_copy(tmp_path, monkeypatch):
    ws = Workspace(tmp_path / "data")
    path = old_file(ws.folder / "Old.gl", 50, monkeypatch)
    broken = migrations_up_to(tmp_path / "new", 51, extra="INSERT INTO no_such_table VALUES (1);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", broken)
    with pytest.raises(UpgradeError) as failed:
        ws.open(path)
    [made] = ws.backups(path)
    assert str(made.path) in str(failed.value)
    assert "не изменён" in str(failed.value)
    assert version_of(path) == 50


def test_the_window_shows_a_failed_update_instead_of_crashing(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.desktop.main_window import MainWindow

    said: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda _w, _t, text: said.append(text))
    )
    ws = Workspace(tmp_path / "data")
    path = old_file(ws.folder / "Old.gl", 50, monkeypatch)
    broken = migrations_up_to(tmp_path / "new", 51, extra="INSERT INTO no_such_table VALUES (1);")
    monkeypatch.setattr(db, "MIGRATIONS_DIR", broken)
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.open_company(path)
    assert win.session is None
    assert len(said) == 1 and "не изменён" in said[0]


# ---- the copy made before an update -----------------------------------------------------


def test_the_last_copy_of_an_older_schema_outlives_the_rotation(tmp_path, monkeypatch):
    """A mistake of an update may show weeks later: the copy made before it is kept
    beyond the newest `keep` copies (the newest UPGRADE_KEEP such copies)."""
    ws = Workspace(tmp_path / "data")
    path = old_file(ws.folder / "Old.gl", 50, monkeypatch)
    conn, _ = ws.open(path)  # backs up the old file, then updates it
    folder = ws.backup_folder(path)
    [before_update] = backup.list_backups(folder)
    made = [backup.make_backup(conn, folder, "Old", keep=3) for _ in range(5)]
    close(conn)
    kept = [b.path for b in backup.list_backups(folder)]
    assert kept == [*reversed(made[2:]), before_update.path]


def test_copies_before_updates_are_not_kept_forever(tmp_path):
    folder = tmp_path / "copies"
    folder.mkdir()
    conn = sqlite3.connect(":memory:")
    made = []
    for version in range(1, 7):  # six updates, each followed by a copy
        conn.execute(f"PRAGMA user_version = {version}")
        made.append(backup.make_backup(conn, folder, "Firma", keep=2))
    conn.close()
    kept = [b.path for b in backup.list_backups(folder)]
    # the newest two, then the last copy of each of the UPGRADE_KEEP schemas before them
    assert kept == list(reversed(made))[: 2 + backup.UPGRADE_KEEP]
