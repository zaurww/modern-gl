"""D86: icons come from Lucide only — no «⋯», «←», «→», «▾» typed as text — and a page
has one blue button."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.widgets import more_button

GLYPHS = ("⋯", "←", "→", "▾", "▼")


@pytest.fixture
def window(qtbot, tmp_path, make_demo):
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def test_more_is_an_icon_not_a_glyph(qtbot):
    b = more_button(list)
    qtbot.addWidget(b)
    assert b.text() == "" and not b.icon().isNull()
    assert b.toolTip() == "Ещё"


@pytest.mark.parametrize("place", ["home", "journal", "bank", "inventory", "directories"])
def test_no_glyph_typed_as_an_icon(window, place):
    window.show_place((place,))
    page = window.stack.currentWidget()
    texts = [b.text() for b in page.findChildren(QPushButton)]
    texts.append(window.sidebar.company.text())
    assert not [t for t in texts if any(g in t for g in GLYPHS)]


def test_directories_have_one_blue_button(window):
    window.show_place(("directories",))
    page = window.stack.currentWidget()
    blue = [b for b in page.findChildren(QPushButton) if b.objectName() == "primary"]
    assert [b.text() for b in blue] == ["+ Новый элемент"]
