"""«Сверить с порталом» on the ƏDV deposit account (D118): a period, the portal's
operations of it against the account's statement, the figures by both sides; what the
books miss loaded in one click; the period marked reconciled — a change seen later, on
the portal or in the books, is said here."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import DepositFetched
from modern_gl.application.bank.deposit_reconciliation import (
    BOOKS_ONLY,
    DIFFERENT,
    PORTAL_ONLY,
    SAME,
    DepositReconciliation,
    changed_since,
    reconcile_deposit,
    reconciled_periods,
)
from modern_gl.desktop.bank_page.deposit_fetch import DepositFetch
from modern_gl.desktop.bank_page.deposit_reconcile_rows import FiguresGrid, ReconciledRows
from modern_gl.desktop.bank_page.portal import summary
from modern_gl.desktop.period_bar import PeriodBar, period_dates
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.dates import next_day
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.domain.periods import MONTH
from modern_gl.i18n import tr

TITLE = "Сверка ƏDV depozit с порталом"


class DepositReconcileDialog(QDialog):
    """Period → sign in → each operation by the portal and by the books → «Отметить
    сверенным»; `changed` — something was written, `chosen_document` — the document
    double-clicked to open."""

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
        self.today = today or date.today()
        self.fetch = DepositFetch(self, session, sign_in, self.today)
        self.fetch.progress.connect(lambda text: self.status.setText(text))
        self.fetch.loaded.connect(self._fetched)
        self.fetch.failed.connect(self._failed)
        self.fetched: DepositFetched | None = None
        self.seen: DepositReconciliation | None = None
        self.changed = False
        self.chosen_document: int | None = None
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
        self.period_bar.changed.connect(self._period_changed)
        root.addWidget(self.period_bar)
        self.history = QLabel()
        self.history.setWordWrap(True)
        root.addWidget(self.history)
        self.status = QLabel(
            tr(
                "Выберите период и нажмите «Сверить с порталом»: операции портала "
                "сравниваются с выпиской счёта."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.rows = ReconciledRows()
        self.rows.document_chosen.connect(self._open_document)
        root.addWidget(self.rows, 1)
        self.figures = FiguresGrid()
        root.addWidget(self.figures)
        self.spacer = QWidget()  # the air under the period while there are no rows
        root.addWidget(self.spacer, 1)
        self._build_actions(root)
        self._suggest_period()
        self._show_history()
        self._show(None)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.close_button = button(tr("Закрыть"), "flat")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        self.load_missing = button(tr("Загрузить недостающие"), "flat")
        self.load_missing.clicked.connect(self.load_missing_operations)
        actions.addWidget(self.load_missing)
        self.mark_button = button(tr("Отметить сверенным"), "primary")
        self.mark_button.clicked.connect(self.mark)
        actions.addWidget(self.mark_button)
        self.reconcile_button = button(tr("Сверить с порталом"), "primary")
        self.reconcile_button.clicked.connect(self.reconcile)
        actions.addWidget(self.reconcile_button)
        root.addLayout(actions)

    def _suggest_period(self) -> None:
        """From the day after the last period reconciled up to today; none — this month."""
        periods = reconciled_periods(self.s.conn, self.s.company_id, self.place)
        if periods:
            following = date.fromisoformat(next_day(periods[-1].date_to))
            if following <= self.today:
                self.period_bar.set_period(following, self.today)

    def period(self) -> tuple[date, date]:
        first, last = self.period_bar.period()
        return first, min(last, self.today)

    def _show_history(self) -> None:
        """The periods reconciled, and what changed in the books (on the portal — once it
        is read) since."""
        conn, cid = self.s.conn, self.s.company_id
        periods = reconciled_periods(conn, cid, self.place)
        texts = []
        if periods:
            names = (
                period_dates(date.fromisoformat(p.date_from), date.fromisoformat(p.date_to))
                for p in periods
            )
            texts.append(tr("Сверено с порталом: {periods}.", periods=", ".join(names)))
        fetched = self.fetched
        if fetched is None:
            changes = changed_since(conn, cid, self.place)
        else:
            changes = changed_since(
                conn, cid, self.place, fetched.operations, fetched.balance, fetched.date_from
            )
        texts += [f"{text}." for text in changes]
        self.history.setText(" ".join(texts))
        self.history.setVisible(bool(texts))
        self.history.setObjectName("warning" if changes else "secondary")
        self.history.style().unpolish(self.history)
        self.history.style().polish(self.history)

    def _show(self, seen: DepositReconciliation | None) -> None:
        """One blue button at a time (D86): reconcile, then mark."""
        self.seen = seen
        self.rows.setVisible(seen is not None)
        self.figures.setVisible(seen is not None)
        self.reconcile_button.setVisible(seen is None)
        self.mark_button.setVisible(seen is not None)
        self.load_missing.setVisible(seen is not None and bool(seen.missing()))
        self.spacer.setVisible(seen is None)
        if seen is None:
            return
        self.resize(max(self.width(), 1040), max(self.height(), 620))
        self.rows.show_rows(seen.rows)
        self.figures.show_figures(seen)
        self.status.setText(verdict(seen))

    def _period_changed(self) -> None:
        if self.seen is not None:  # the rows were of another period
            self.fetched = None
            self.status.setText(tr("Период изменён — сверьте его с порталом."))
            self._show(None)

    # ---- the portal -----------------------------------------------------------------

    def reconcile(self) -> None:
        first, last = self.period()
        if last < first:
            self.status.setText(tr("начало периода позже конца"))
            return
        self.reconcile_button.setEnabled(False)
        if self.fetch.start(first, last):
            self.status.setText(tr("Загрузка с портала…"))
        else:
            self.reconcile_button.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.reconcile_button.setEnabled(True)
        self.status.setText(message)

    def _fetched(self, fetched: DepositFetched) -> None:
        self.reconcile_button.setEnabled(True)
        self.fetched = fetched
        self._refresh()

    def _refresh(self) -> None:
        fetched = self.fetched
        if fetched is None:
            return
        seen = reconcile_deposit(
            self.s.conn,
            self.s.company_id,
            self.place,
            fetched.operations,
            fetched.balance,
            fetched.date_from,
            fetched.date_to,
        )
        self._show(seen)
        self._show_history()

    # ---- writing --------------------------------------------------------------------

    def load_missing_operations(self) -> None:
        """What only the portal has, into the books — as «Загрузить с портала» would."""
        fetched, seen = self.fetched, self.seen
        if fetched is None or seen is None:
            return
        try:
            done = self.s.ledger.bank.import_vat_deposit(
                self.s.company_id,
                self.place,
                fetched.operations,
                fetched.balance,
                (fetched.date_from, fetched.date_to),
                take={op.reference for op in seen.missing()},
            )
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.changed = True
        self._refresh()
        self.status.setText(f"{summary(done)}. {self.status.text()}")

    def mark(self) -> None:
        seen = self.seen
        if seen is None:
            return
        try:
            self.s.ledger.bank.mark_deposit_reconciled(self.s.company_id, self.place, seen)
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.changed = True
        self._show_history()
        self.mark_button.setVisible(False)
        self.load_missing.setVisible(False)
        self.close_button.setText(tr("Готово"))
        self.status.setText(
            tr(
                "Период {period} отмечен сверенным: если потом на портале или в программе он "
                "изменится, здесь будет предупреждение.",
                period=period_dates(*self.period()),
            )
        )

    def _open_document(self, document_id: int) -> None:
        self.chosen_document = document_id
        self.accept()


def verdict(seen: DepositReconciliation) -> str:
    """What the reconciliation found, in one line over the rows."""
    if seen.agreed:
        return tr("Всё совпадает: операции и остатки портала и программы одинаковы.")
    count = {state: 0 for state in (SAME, DIFFERENT, PORTAL_ONLY, BOOKS_ONLY)}
    for row in seen.rows:
        count[row.state] += 1
    text = tr(
        "Совпадает {same}, отличается {different}, только на портале {portal}, только в "
        "программе {books}",
        same=count[SAME],
        different=count[DIFFERENT],
        portal=count[PORTAL_ONLY],
        books=count[BOOKS_ONLY],
    )
    if seen.difference:
        text += tr("; остатки на конец расходятся на {diff} ₼", diff=format_minor(seen.difference))
    return text + "."
