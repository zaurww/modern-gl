"""Backups in sight (D97): the last copy on «Bu gün», «Резервные копии» in the company
menu — a copy now and a second folder (a flash drive, a cloud folder) every copy goes to."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.ledger import PostingInput
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.backups_dialog import MIRROR_SETTING, BackupsDialog
from modern_gl.desktop.home_page import HomePage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure import backup
from tests.test_backup import company, documents


def test_a_backup_goes_to_the_second_folder_too(tmp_path):
    ws = Workspace(tmp_path / "data", mirror=tmp_path / "flash")
    path, conn, ledger, cid, (a, b) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    made = ws.auto_backup(conn, path)
    assert made is not None
    copy = tmp_path / "flash" / "Firma" / made.name
    assert copy.exists() and documents(copy) == 1
    backup.check(copy, full=True)
    assert not list(copy.parent.glob("*.part"))
    conn.close()


def test_a_missing_second_folder_does_not_lose_the_first_copy(tmp_path):
    blocked = tmp_path / "not a folder"
    blocked.write_text("a file where the folder should be")
    ws = Workspace(tmp_path / "data", mirror=blocked)
    path, conn, *_ = company(ws)
    with pytest.raises(backup.BackupError, match="во вторую папку"):
        ws.backup_now(conn, path)
    assert len(ws.backups(path)) == 1  # made in the company's own folder
    conn.close()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, make_demo):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(QApplication.instance())
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(Workspace(tmp_path), settings)
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def home_backup_line(win) -> tuple[str, str]:
    page = win.pages[("home",)]
    assert isinstance(page, HomePage)
    section = page.sections[-1]
    line = section.lines[0]
    return line.text.text(), line.figure.text()


def test_home_shows_the_last_copy_and_the_dialog_makes_one(window, qtbot, tmp_path):
    assert home_backup_line(window)[0] == "Копий ещё нет"
    dialog = BackupsDialog(
        window.workspace, window.conn, window.company_path, window.settings, window
    )
    qtbot.addWidget(dialog)
    assert dialog.last.text() == "Копий ещё нет"
    dialog.set_mirror(tmp_path / "cloud")
    assert window.settings.value(MIRROR_SETTING) == str(tmp_path / "cloud")
    dialog.backup_now()
    made = window.workspace.backups(window.company_path)[0]
    assert dialog.last.text() == f"Последняя копия: {made.made_at:%d.%m.%Y %H:%M}"
    assert (tmp_path / "cloud" / window.company_path.stem / made.path.name).exists()
    window.pages[("home",)].refresh()
    assert home_backup_line(window) == ("Последняя копия", f"{made.made_at:%d.%m.%Y %H:%M}")
    dialog.set_mirror(None)
    assert window.workspace.mirror is None and window.settings.value(MIRROR_SETTING) == ""
