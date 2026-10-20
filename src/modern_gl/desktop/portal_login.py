"""Signing in to new.e-taxes.gov.az inside the program: the portal's own page in a built-in
browser (ASAN İmza as always); when the page has its token, the window takes it and closes.

The same thing etaxes-ext does in Chrome (`lib/auth.js`: the token is in the page's
`localStorage['aztax-jwt']`). The browser keeps its profile (cookies) in the program's
data folder, so a second sign-in within the portal session is quick."""

from __future__ import annotations

import base64
import json
import time

from PySide6.QtCore import QStandardPaths, QTimer, QUrl
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from modern_gl.desktop.theme import fonts
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import BASE_URL, PORTAL_TOKEN_KEY


def token_payload(token: str) -> dict:
    """The JWT's payload (VÖEN, name, expiry); {} if it is not one."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}


def token_alive(token: str | None, margin: int = 60) -> bool:
    """A token that will still work for a minute (it lives 10)."""
    if not token:
        return False
    expires = token_payload(token).get("exp")
    return isinstance(expires, int) and expires - margin > time.time()


class PortalLoginDialog(QDialog):
    """The portal page; `token` is set when the user has signed in."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # imported here: the web engine is big and only this window needs it
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.token: str | None = None
        self.setWindowTitle(tr("Вход на портал e-taxes"))
        self.resize(1100, 780)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        hint = QLabel(tr("Войдите через ASAN İmza и выберите компанию — окно закроется само."))
        hint.setObjectName("secondary")
        hint.setFont(fonts().small)
        root.addWidget(hint)
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(_profile(), self.view))
        root.addWidget(self.view, 1)
        self.view.load(QUrl(BASE_URL))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._look_for_token)
        self.timer.start(1000)

    def _look_for_token(self) -> None:
        key = json.dumps(PORTAL_TOKEN_KEY)  # an error page has no storage: no token yet
        script = (
            f"(() => {{ try {{ return localStorage.getItem({key}); }} "
            "catch (e) { return null; } })()"
        )
        self.view.page().runJavaScript(script, 0, self._found)

    def _found(self, token: object) -> None:
        # a token of the portal user is there before a company is chosen: wait for its VÖEN
        if isinstance(token, str) and token_alive(token) and _company_of(token):
            self.timer.stop()
            self.token = token
            self.accept()


_PROFILE: list = []


def _profile():
    """One browser profile for the program's life, its cookies kept on disk: it must outlive
    every page that uses it, so it belongs to the application, not to a window."""
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWidgets import QApplication

    if not _PROFILE:
        profile = QWebEngineProfile("modern-gl-etaxes", QApplication.instance())
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        profile.setPersistentStoragePath(f"{folder}/etaxes-browser")
        _PROFILE.append(profile)
    return _PROFILE[0]


def _company_of(token: str) -> str:
    payload = token_payload(token)
    return "".join(
        ch for ch in str(payload.get("voen") or payload.get("tin") or "") if ch.isdigit()
    )


def company_name(token: str) -> str:
    payload = token_payload(token)
    for key in ("organizationName", "orgName", "taxpayerName", "name", "fullName"):
        if payload.get(key):
            return str(payload[key])
    return ""


def company_tin(token: str) -> str:
    return _company_of(token)


def sign_in(parent: QWidget | None = None) -> str | None:
    """Open the portal and wait for the user to sign in; the token, or None."""
    dialog = PortalLoginDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.token
    return None
