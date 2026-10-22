"""«Save as»: the company goes on in another file (anywhere, under a new name); the old
file stays as it was; files outside the folder are remembered and listed."""

from __future__ import annotations

import sqlite3

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.workspace import TRASH, Workspace, company_name


def company(ws: Workspace, name: str = "Firma"):
    path = ws.create(name, chart=None)
    conn, cid = ws.open(path)
    ledger = Ledger(conn)
    a = ledger.add_account(cid, "50", "Касса", account_class="asset")
    b = ledger.add_account(cid, "80", "Капитал", account_class="equity")
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    return path, conn, ledger, cid, (a, b)


def total(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT SUM(amount) FROM postings").fetchone()[0]
    finally:
        conn.close()


def test_save_as_copies_under_a_new_name_and_keeps_the_old_file(tmp_path):
    ws = Workspace(tmp_path / "data")
    path, conn, *_ = company(ws)
    target = tmp_path / "flash" / "Firma 2027.gl"
    ws.save_as(conn, path, target, "Firma 2027")
    conn.close()
    assert total(target) == total(path) == 10000  # 100.00 manat in kopecks
    assert company_name(target) == "Firma 2027"
    assert company_name(path) == "Firma"  # the old file is untouched
    assert ws.files == [target.absolute()]
    assert [c.name for c in ws.companies()] == ["Firma", "Firma 2027"]
    # a new run with the stored list sees it too; a missing file is just not listed
    again = Workspace(tmp_path / "data", [str(target), str(tmp_path / "gone.gl")])
    assert [c.path for c in again.companies()] == [path, target]


def test_save_as_inside_the_folder_is_not_remembered_twice(tmp_path):
    ws = Workspace(tmp_path)
    path, conn, *_ = company(ws)
    ws.save_as(conn, path, tmp_path / "Copy.gl", "Copy")
    conn.close()
    assert ws.files == []
    assert [c.name for c in ws.companies()] == ["Copy", "Firma"]


def test_save_as_refuses_the_open_file_and_an_empty_name(tmp_path):
    ws = Workspace(tmp_path)
    path, conn, *_ = company(ws)
    with pytest.raises(backup.BackupError):
        ws.save_as(conn, path, path, "Firma")
    with pytest.raises(ValidationError):
        ws.save_as(conn, path, tmp_path / "x.gl", "  ")
    conn.close()


def test_rename_is_audited(tmp_path):
    ws = Workspace(tmp_path)
    _path, conn, ledger, cid, _ = company(ws)
    ledger.rename_company(cid, " Yeni ad ")
    row = conn.execute(
        "SELECT action, details FROM audit_events WHERE entity = 'company' ORDER BY id DESC"
    ).fetchone()
    assert row["action"] == "rename" and "Yeni ad" in row["details"]
    assert conn.execute("SELECT name FROM companies").fetchone()[0] == "Yeni ad"
    conn.close()


def test_deleting_a_file_outside_the_folder_forgets_it(tmp_path):
    ws = Workspace(tmp_path / "data")
    path, conn, *_ = company(ws)
    target = tmp_path / "elsewhere" / "Other.gl"
    ws.save_as(conn, path, target, "Other")
    conn.close()
    moved = ws.delete(target)
    assert moved.parent == tmp_path / "data" / TRASH and not target.exists()
    assert ws.files == []


def test_window_save_as_goes_on_in_the_new_file(qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    from modern_gl.desktop.main_window import MainWindow

    ws = Workspace(tmp_path / "data")
    path, conn, _ledger, cid, (a, b) = company(ws)
    conn.close()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(ws, settings)
    qtbot.addWidget(win)
    win.start()
    target = tmp_path / "elsewhere" / "Firma 2027"  # the extension is added
    assert win.save_as_to(target, "Firma 2027")
    assert win.company_path == target.with_suffix(".gl")
    assert win.open_session.company_name == "Firma 2027"
    win.open_session.ledger.post_new(cid, "2026-03-02", [PostingInput(a, b, "50")])
    win.shutdown()
    assert total(target.with_suffix(".gl")) == 15000
    assert total(path) == 10000
    assert settings.value("company_files", [], type=list) == [str(target.with_suffix(".gl"))]


def test_new_company_anywhere_is_remembered(tmp_path):
    ws = Workspace(tmp_path / "data")
    target = tmp_path / "Clients" / "Alfa.gl"
    target.parent.mkdir()
    assert ws.create("Alfa", path=target) == target
    assert ws.files == [target.absolute()]
    assert [c.path for c in ws.companies()] == [target]
    # replacing an existing file gives a fresh company, nothing of the old one
    old, conn, *_ = company(ws, "Old")
    conn.close()
    ws.create("Fresh", chart=None, path=old)
    assert company_name(old) == "Fresh"
    check = sqlite3.connect(old)
    assert check.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == 0
    check.close()
    assert not list(tmp_path.rglob("*.part"))


def test_window_asks_where_to_put_a_new_company(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from modern_gl.desktop.main_window import MainWindow

    ws = Workspace(tmp_path / "data")
    company(ws)[1].close()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(ws, settings)
    qtbot.addWidget(win)
    win.start()
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("Beta", True)),
    )
    monkeypatch.setattr(  # the whole program, not a warehouse only (D90)
        "modern_gl.desktop.main_window.company_files.QInputDialog.getItem",
        staticmethod(lambda _w, _t, _l, kinds, *a, **k: (kinds[0], True)),
    )
    chosen = tmp_path / "Clients" / "Beta MMC"  # the extension is added
    chosen.parent.mkdir()
    answer = [""]  # cancelled first: nothing is created
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (answer[0], "")),
    )
    assert not win.create_company()
    assert [c.name for c in ws.companies()] == ["Firma"]
    answer[0] = str(chosen)
    assert win.create_company()
    assert win.company_path == chosen.with_suffix(".gl")
    assert win.open_session.company_name == "Beta"
    assert settings.value("company_files", [], type=list) == [str(chosen.with_suffix(".gl"))]
    win.shutdown()
