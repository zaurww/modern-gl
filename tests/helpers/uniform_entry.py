"""Shared from test_uniform_entry.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.desktop import theme
from tests.helpers.qt import running_app


def shown(qtbot, page):
    theme.apply(running_app())
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    return page
