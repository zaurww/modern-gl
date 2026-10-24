"""The ƏDV deposit account's operations read from the portal for a window: signed in for
this company (D113), off the window's thread — the window stays alive. Both the loading
(D112) and the reconciliation (D118) windows read through it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import DepositFetched, fetch_deposit
from modern_gl.application.bank.deposit_reconciliation import changed_since
from modern_gl.desktop import portal_login
from modern_gl.desktop.eqaime_portal_loader import PortalLoader
from modern_gl.desktop.portal_company import company_token
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.etaxes import EtaxesClient


class DepositFetch(QObject):
    """`start(first, last)` → `progress`…, then `loaded(DepositFetched)` or `failed(text)`."""

    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        window: QWidget,
        session: Session,
        sign_in: Callable[..., str | None] | None,
        today: date,
    ) -> None:
        super().__init__(window)
        self.window, self.s, self.sign_in, self.today = window, session, sign_in, today
        self.worker: QThread | None = None
        self.loader: PortalLoader | None = None

    def start(self, first: date, last: date) -> bool:
        """Sign in (the portal's page, unless signed in already) and read the operations
        from `first` up to today; False — not signed in, nothing started."""
        token = company_token(self.window, self.s, self.sign_in)  # this company's, D113
        if not token:
            return False
        tin = portal_login.company_tin(token)
        client, today = EtaxesClient(token), self.today
        self.worker = QThread(self)
        self.loader = PortalLoader(
            lambda progress: fetch_deposit(client, first, today, tin, progress, last)
        )
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.progress.connect(self.progress.emit)
        self.loader.loaded.connect(self.loaded.emit)
        self.loader.failed.connect(self._failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()
        return True

    def _failed(self, message: str) -> None:
        portal_login.forget_token()  # a new sign-in next time
        self.failed.emit(message)


def reconciled_changes(
    session: Session, place: BankPlace, fetched: DepositFetched | None
) -> list[str]:
    """What changed in the periods reconciled (D118): in the books always, on the portal
    once it is read for them — the same words in the loading and reconciling windows."""
    conn, cid = session.conn, session.company_id
    if fetched is None:
        return changed_since(conn, cid, place)
    return changed_since(conn, cid, place, fetched.operations, fetched.balance, fetched.date_from)
