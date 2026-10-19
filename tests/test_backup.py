"""Backups: consistent checked copies, the newest 30 kept, restore that can be undone,
a backup before a schema update, damaged files refused."""

from __future__ import annotations

import sqlite3

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from modern_gl.infrastructure.workspace import Workspace


def company(ws: Workspace, name: str = "Firma"):
    path = ws.create(name, chart=None)
    conn, cid = ws.open(path)
    ledger = Ledger(conn)
    a = ledger.add_account(cid, "50", "Касса", account_class="asset")
    b = ledger.add_account(cid, "80", "Капитал", account_class="equity")
    return path, conn, ledger, cid, (a, b)


def documents(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()


def test_backup_is_a_checked_copy_and_only_the_newest_are_kept(tmp_path):
    ws = Workspace(tmp_path / "data")
    path, conn, ledger, cid, (a, b) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    folder = ws.backup_folder(path)
    made = [backup.make_backup(conn, folder, "Firma", keep=3) for _ in range(5)]
    kept = backup.list_backups(folder)
    assert [k.path for k in kept] == list(reversed(made[2:]))  # newest first
    assert documents(kept[0].path) == 1
    backup.check(kept[0].path)
    assert not list(folder.glob("*.part"))
    conn.close()


def test_closing_backs_up_only_when_something_changed(tmp_path):
    ws = Workspace(tmp_path / "data")
    path, conn, ledger, cid, (a, b) = company(ws)
    assert ws.auto_backup(conn, path) is not None
    assert ws.auto_backup(conn, path) is None  # nothing new
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    assert ws.auto_backup(conn, path) is not None
    assert len(ws.backups(path)) == 2
    conn.close()


def test_restore_brings_back_the_backup_and_keeps_the_current_file(tmp_path):
    ws = Workspace(tmp_path / "data")
    path, conn, ledger, cid, (a, b) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    saved = ws.auto_backup(conn, path)
    ledger.post_new(cid, "2026-03-02", [PostingInput(a, b, "200")])
    conn.close()

    safety = ws.restore(saved, path)
    assert documents(path) == 1
    assert documents(safety) == 2  # the restore itself can be undone
    conn, _ = ws.open(path)  # the restored file opens and works
    Ledger(conn).post_new(cid, "2026-03-03", [PostingInput(a, b, "300")])
    conn.close()
    assert documents(path) == 2


def test_damaged_file_is_refused(tmp_path):
    ws = Workspace(tmp_path / "data")
    bad = ws.folder / "Broken.gl"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 50 + b"garbage" * 200)
    with pytest.raises(backup.BackupError, match="повреждён"):
        ws.open(bad)


def test_old_file_is_backed_up_before_the_schema_update(tmp_path):
    ws = Workspace(tmp_path / "data")
    path = ws.folder / "Old.gl"
    old = sqlite3.connect(path, isolation_level=None)
    old.execute("PRAGMA foreign_keys = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version > 7:
            break
        sql = migration.read_text(encoding="utf-8")
        old.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
    old.execute("INSERT INTO companies (name, created_at) VALUES ('Old', 'now')")
    old.close()
    conn, _ = ws.open(path)
    conn.close()
    [made] = ws.backups(path)
    assert "до обновления" in made.path.name
    check = sqlite3.connect(made.path)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 7  # as it was before
    check.close()
    conn, _ = ws.open(path)  # already current: no second backup
    conn.close()
    assert len(ws.backups(path)) == 1


def test_window_backs_up_on_close_and_restores(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.desktop.main_window import MainWindow

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    )
    ws = Workspace(tmp_path / "data")
    path, conn, ledger, cid, (a, b) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    conn.close()
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.start()
    win.ledger.post_new(cid, "2026-03-02", [PostingInput(a, b, "200")])
    win.shutdown()
    [first] = ws.backups(path)
    assert documents(first.path) == 2

    win.start()
    win.ledger.post_new(cid, "2026-03-03", [PostingInput(a, b, "300")])
    assert win.restore_from(first.path, path)
    assert win.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    win.shutdown()


def test_copy_of_open_database_is_consistent(tmp_path):
    conn = connect(tmp_path / "live.gl")
    ledger = Ledger(conn)
    cid = ledger.create_company("Live")
    target = backup.copy_to(conn, tmp_path / "copy" / "Live.gl")
    assert sqlite3.connect(target).execute("SELECT name FROM companies").fetchone()[0] == "Live"
    conn.close()
    assert cid == 1


def test_failed_copy_leaves_no_partial_file(tmp_path):
    ws = Workspace(tmp_path / "data")
    _, conn, *_ = company(ws)
    target = tmp_path / "copy.gl"
    conn.close()  # backing up a closed connection fails half-way
    with pytest.raises(sqlite3.ProgrammingError):
        backup.copy_to(conn, target)
    assert list(tmp_path.glob("copy.gl*")) == []
