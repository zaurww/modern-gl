"""Shared from test_desktop.py (moved here: other test modules use it too)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import (
    QApplication,
)

from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow


@pytest.fixture(name="desktop_workspace")
def workspace(tmp_path, make_demo):
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("ДЕМО ООО")
    make_demo(path)
    return ws


@pytest.fixture(name="desktop_window")
def window(qtbot, desktop_workspace):
    theme.apply(QApplication.instance())
    win = MainWindow(desktop_workspace)
    qtbot.addWidget(win)
    win.start()  # it opens on «Bu gün» (D86); these tests start from the journal
    win.session.working_date = date(2026, 3, 5)
    win.show_place(("journal",))
    win.show()
    yield win
    win.shutdown()
