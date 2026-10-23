"""«Загрузить с портала» on the ƏDV deposit account (D112): a period chosen as in the
e-qaimə window (a day, a week, a month or any dates), what was loaded before shown and a
period loaded already not loaded again unasked (D115); signed in to the portal for this
company already — at once, else its page (D113); the operations read off the window's
thread."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import (
    DepositFetched,
    fetch_deposit,
    loaded_already,
    loaded_spans,
    next_to_load,
    portal_loads,
    unfinished_days,
)
from modern_gl.application.ledger.bank_deposit import DepositImported
from modern_gl.desktop import portal_login
from modern_gl.desktop.eqaime_portal_loader import PortalLoader
from modern_gl.desktop.period_bar import PeriodBar, period_dates
from modern_gl.desktop.portal_company import company_token
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.periods import MONTH
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient

TITLE = "ƏDV depozit с портала"


class DepositDialog(QDialog):
    """Period → sign in → the portal's operations of the period into the account's
    statements; `imported` — what the import did."""

    def __init__(
        self,
        session: Session,
        place: BankPlace,
        parent: QWidget | None = None,
        sign_in: Callable[..., str | None] | None = None,
        today: date | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.place = place
        self.sign_in = sign_in
        self.today = today or date.today()
        self.worker: QThread | None = None
        self.loader: PortalLoader | None = None
        self.imported: DepositImported | None = None
        self.loads = portal_loads(session.conn, session.company_id, place)
        self.setWindowTitle(tr(TITLE))
        self.resize(860, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        title = QLabel(tr(TITLE))
        title.setFont(fonts().title)
        root.addWidget(title)
        account = QLabel(place.name)
        account.setObjectName("secondary")
        root.addWidget(account)
        self.period_bar = PeriodBar(self.today, MONTH, through_today=True)
        self.period_bar.changed.connect(self._show_loaded)
        root.addWidget(self.period_bar)
        self.loaded = QLabel()
        self.loaded.setWordWrap(True)
        root.addWidget(self.loaded)
        self.status = QLabel(
            tr(
                "Выберите период и нажмите «Загрузить с портала»: если вход на портал не "
                "открыт, откроется его страница (ASAN İmza)."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)
        self._build_actions(root)
        self._suggest_period()
        self._show_loaded()

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        actions.addStretch(1)
        close = button(tr("Закрыть"), "flat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.load_button = button(tr("Загрузить с портала"), "primary")
        self.load_button.clicked.connect(self.load)
        actions.addWidget(self.load_button)
        root.addLayout(actions)

    def _suggest_period(self) -> None:
        """From the day after the last one loaded (a day loaded before it ended — from it)
        up to today; nothing loaded yet — this month."""
        start = next_to_load(self.loads)
        if start is None:
            return
        following = date.fromisoformat(start)
        if following <= self.today:
            self.period_bar.set_period(following, self.today)

    def period(self) -> tuple[date, date]:
        """The period chosen, up to today: the portal has no operations of tomorrow."""
        first, last = self.period_bar.period()
        return first, min(last, self.today)

    def _show_loaded(self) -> None:
        spans = loaded_spans(self.loads)
        if not self.loads:
            self.loaded.setObjectName("secondary")
            self.loaded.setText(tr("С портала в этот счёт ещё ничего не загружалось."))
        else:
            text = " ".join(self._loaded_texts(spans))
            first, last = self.period()
            again = loaded_already(self.loads, first.isoformat(), last.isoformat())
            if again:
                text += " " + tr("Выбранный период уже загружен.")
            self.loaded.setObjectName("warning" if again else "secondary")
            self.loaded.setText(text)
        self.loaded.style().unpolish(self.loaded)
        self.loaded.style().polish(self.loaded)

    def _loaded_texts(self, spans: list[tuple[str, str]]) -> list[str]:
        texts = []
        if spans:
            periods = (period_dates(date.fromisoformat(a), date.fromisoformat(b)) for a, b in spans)
            texts.append(tr("Уже загружено с портала: {periods}.", periods=", ".join(periods)))
        unfinished = [
            date.fromisoformat(d).strftime("%d.%m.%Y") for d in unfinished_days(self.loads)
        ]
        if unfinished:
            texts.append(
                tr(
                    "{days} загружено, пока день не кончился: поздние операции этого дня "
                    "возьмутся при следующей загрузке.",
                    days=", ".join(unfinished),
                )
            )
        return texts

    # ---- loading -------------------------------------------------------------------

    def load(self) -> None:
        first, last = self.period()
        if last < first:
            self.status.setText(tr("начало периода позже конца"))
            return
        if loaded_already(self.loads, first.isoformat(), last.isoformat()) and not self._again(
            first, last
        ):
            return
        token = company_token(self, self.s, self.sign_in)  # this company's, D113
        if not token:
            return
        tin = portal_login.company_tin(token)
        client, today = EtaxesClient(token), self.today
        self._start(lambda progress: fetch_deposit(client, first, today, tin, progress, last))

    def _again(self, first: date, last: date) -> bool:
        question = tr(
            "Период {period} уже загружен с портала. Загрузить снова?\n\nДвойных операций "
            "не будет: добавятся только новые, появившиеся на портале после прошлой загрузки.",
            period=period_dates(first, last),
        )
        answer = QMessageBox.question(self, tr(TITLE), question)
        return answer == QMessageBox.StandardButton.Yes

    def _start(self, job: Callable[[Callable[[str], None]], DepositFetched]) -> None:
        """Talk to the portal off the window's thread: the window stays alive."""
        self.load_button.setEnabled(False)
        self.status.setText(tr("Загрузка с портала…"))
        self.worker = QThread(self)
        self.loader = PortalLoader(job)
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.progress.connect(self.status.setText)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()

    def _failed(self, message: str) -> None:
        portal_login.forget_token()  # a new sign-in next time
        self.load_button.setEnabled(True)
        self.status.setText(message)

    def _loaded(self, fetched: DepositFetched) -> None:
        self.load_button.setEnabled(True)
        try:
            self.imported = self.s.ledger.bank.import_vat_deposit(
                self.s.company_id,
                self.place,
                fetched.operations,
                fetched.balance,
                (fetched.date_from, fetched.date_to),
            )
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.accept()


def summary(done: DepositImported) -> str:
    """What the import did, in one line after it."""
    text = tr(
        "С портала: проведено {posted}, не разнесено {drafts}",
        posted=done.posted,
        drafts=len(done.drafts),
    )
    if done.counterparties:
        text += tr(", новых контрагентов {n}", n=done.counterparties)
    if not (done.posted or done.drafts or done.linked):
        text += tr(" — новых операций нет")
    return text
