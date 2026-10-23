"""«Загрузить с портала» on the ƏDV deposit account (D110): signed in to the portal for
this company already — at once, else its page (D111); the operations read off the
window's thread."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import (
    DepositFetched,
    fetch_deposit,
)
from modern_gl.desktop import portal_login
from modern_gl.desktop.eqaime_portal_loader import PortalLoader
from modern_gl.desktop.portal_company import company_token
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import ask_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient


class DepositPortal(QObject):
    """Loads the deposit account's operations from the portal into its statements."""

    imported = Signal()  # something was written: the page reads itself again

    def __init__(
        self,
        session: Session,
        parent: QWidget,
        sign_in: Callable[..., str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.window = parent
        self.sign_in = sign_in
        self.worker: QThread | None = None
        self.loader: PortalLoader | None = None
        self.place: BankPlace | None = None

    def load(self, place: BankPlace, start: date) -> None:
        day = ask_date(
            self.window,
            tr("ƏDV depozit с портала"),
            tr("Загрузить операции с даты по сегодня:"),
            start,
        )
        if day is None:
            return
        token = company_token(self.window, self.s, self.sign_in)
        if not token:
            return
        self.place = place
        tin = portal_login.company_tin(token)
        client, today = EtaxesClient(token), date.today()
        self._start(lambda progress: fetch_deposit(client, day, today, tin, progress))

    def _start(self, job: Callable[[Callable[[str], None]], DepositFetched]) -> None:
        """Talk to the portal off the window's thread: the window stays alive."""
        self.s.notify(tr("Загрузка с портала…"))
        self.worker = QThread(self)
        self.loader = PortalLoader(job)
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.loaded.connect(self.loaded)
        self.loader.failed.connect(self.failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()

    def failed(self, message: str) -> None:
        portal_login.forget_token()  # a new sign-in next time
        self.s.notify(message)

    def loaded(self, fetched: DepositFetched) -> None:
        place = self.place
        if place is None:
            return
        try:
            done = self.s.ledger.bank.import_vat_deposit(
                self.s.company_id, place, fetched.operations, fetched.balance
            )
        except LedgerError as e:
            self.s.notify(str(e))
            return
        text = tr(
            "С портала: проведено {posted}, не разнесено {drafts}",
            posted=done.posted,
            drafts=len(done.drafts),
        )
        if done.counterparties:
            text += tr(", новых контрагентов {n}", n=done.counterparties)
        self.s.notify(text)
        self.imported.emit()
