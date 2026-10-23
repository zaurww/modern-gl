"""Signing in to new.e-taxes.gov.az inside the program: the portal's own page in a built-in
browser (ASAN İmza as always); when the page has its token, the window takes it and closes.

The same thing etaxes-ext does in Chrome (`lib/auth.js`: the token is in the page's
`localStorage['aztax-jwt']`). The browser keeps its profile (cookies) in the program's
data folder, so a second sign-in within the portal session is quick."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable

from PySide6.QtCore import QStandardPaths, QTimer, QUrl
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
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

    def __init__(self, parent: QWidget | None = None, company: str = "") -> None:
        super().__init__(parent)
        self.company = company  # the VÖEN wanted (D113): a token of another firm waits
        # imported here: the web engine is big and only this window needs it
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.token: str | None = None
        self.setWindowTitle(tr("Вход на портал e-taxes"))
        self.resize(1100, 780)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        hint = QLabel(
            tr(
                "Войдите через ASAN İmza и выберите компанию с VÖEN {tin} — окно закроется само.",
                tin=company,
            )
            if company
            else tr("Войдите через ASAN İmza и выберите компанию — окно закроется само.")
        )
        hint.setObjectName("secondary")
        hint.setFont(fonts().small)
        top = QHBoxLayout()
        top.addWidget(hint, 1)
        reload = button(tr("Обновить страницу"), "flat")
        reload.clicked.connect(lambda: self.view.reload())
        top.addWidget(reload)
        root.addLayout(top)
        self.state = QLabel(waiting_for(None, company))  # what the window waits for now
        self.state.setFont(fonts().small)
        root.addWidget(self.state)
        self.view = QWebEngineView(self)
        self.view.setPage(_page_class()(_profile(), self.view))
        root.addWidget(self.view, 1)
        self.view.load(QUrl(LOGIN_URL))
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
        found = token if isinstance(token, str) else None
        waiting = waiting_for(found, self.company)
        self.state.setText(waiting)
        if not waiting and found:
            self.timer.stop()
            self.token = found
            self.accept()


def waiting_for(token: str | None, company: str = "") -> str:
    """What the sign-in window still waits for, said to the user; '' — the token is taken.
    A window that waits silently looks hung."""
    if not token:
        return tr("Ждём входа на портал…")
    if not token_alive(token):
        return tr("Вход на портал устарел — войдите ещё раз или обновите страницу")
    tin = _company_of(token)
    if not tin:
        return tr("Вход выполнен — выберите на портале компанию")
    if company and tin != company:
        return tr(
            "На портале выбрана фирма с VÖEN {tin}, а нужна VÖEN {own} — выберите её",
            tin=tin,
            own=company,
        )
    return ""


LOGIN_URL = f"{BASE_URL}/eportal/login"

_PAGE: list = []


def _page_class():
    """A page that opens links meant for a new tab («Daxil ol» on the portal is one) in
    itself: a built-in browser has no tabs, and without this such a click does nothing."""
    if not _PAGE:
        from PySide6.QtWebEngineCore import QWebEnginePage

        class SingleTabPage(QWebEnginePage):
            def createWindow(self, _type):
                # the new page only learns where it goes: send that address here
                popup = QWebEnginePage(self.profile(), self)
                popup.urlChanged.connect(lambda url: self._take(popup, url))
                return popup

            def _take(self, popup, url: QUrl) -> None:
                if url.isValid() and not url.isEmpty():
                    self.setUrl(url)
                    popup.deleteLater()

        _PAGE.append(SingleTabPage)
    return _PAGE[0]


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


def sign_in(parent: QWidget | None = None, company: str = "") -> str | None:
    """Open the portal and wait for the user to sign in (for the firm with the VÖEN
    `company`, if given); the token, or None."""
    dialog = PortalLoginDialog(parent, company)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.token
    return None


_TOKEN: list[str] = []  # the portal session open in the program: in memory only (D72)


def portal_token(
    parent: QWidget | None = None,
    ask: Callable[..., str | None] | None = None,
    company: str = "",
) -> str | None:
    """The token of the portal session open in the program, or a sign-in: the portal's
    page, which closes by itself at once while the portal still knows the browser (D112).
    `company`: the VÖEN wanted — a token of another firm is not taken (D113)."""
    if _TOKEN and token_alive(_TOKEN[0]) and company in ("", _company_of(_TOKEN[0])):
        return _TOKEN[0]
    token = ask(parent) if ask else sign_in(parent, company)
    if token:
        _TOKEN[:] = [token]
    return token


def forget_token() -> None:
    """The portal refused the token: the next call signs in again."""
    _TOKEN.clear()
