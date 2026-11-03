"""The portal window (D45): built without the real browser — a fake engine stands in."""

from __future__ import annotations

import sys
import types

from PySide6.QtWidgets import QWidget

from modern_gl.desktop import portal_login


class FakeView(QWidget):
    """What PortalLoginDialog asks of QWebEngineView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loaded = None
        self.reloads = 0

    def setPage(self, page):  # noqa: N802 — the Qt name
        self._page = page

    def page(self):
        return self._page

    def load(self, url):
        self.loaded = url

    def reload(self):
        self.reloads += 1


def test_the_portal_window_builds_its_browser_first(qtbot, monkeypatch):
    """0.1.2 at the colleague's: «Обновить страницу» was connected to the browser before
    it existed — AttributeError 'view' and no portal at all."""
    fake = types.ModuleType("PySide6.QtWebEngineWidgets")
    fake.QWebEngineView = FakeView  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", fake)
    monkeypatch.setattr(portal_login, "_page_class", lambda: lambda _profile, _parent: object())
    monkeypatch.setattr(portal_login, "_profile", lambda: None)

    dialog = portal_login.PortalLoginDialog(None, "1234567890")
    qtbot.addWidget(dialog)
    dialog.timer.stop()

    assert isinstance(dialog.view, FakeView)
    assert dialog.view.loaded is not None
    assert dialog.view.loaded.toString() == portal_login.LOGIN_URL
    assert "1234567890" in dialog.state.text() or dialog.state.text()
