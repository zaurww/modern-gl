"""Shared from test_uniform_entry.py (moved here: other test modules use it too)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from modern_gl.desktop import theme


def shown(qtbot, page):
    theme.apply(QApplication.instance())
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    return page
