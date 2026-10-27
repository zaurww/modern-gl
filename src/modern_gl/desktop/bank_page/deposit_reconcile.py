"""«Сверить с порталом» on the ƏDV deposit account (D118): a period, the portal's
operations of it against the account's statement, the figures by both sides; what the
books miss loaded in one click; the period marked reconciled — a change seen later, on
the portal or in the books, is said here."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QLabel, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import DepositFetched
from modern_gl.application.bank.deposit_reconciliation import (
    BOOKS_ONLY,
    DIFFERENT,
    PORTAL_ONLY,
    SAME,
    DepositReconciliation,
    Figures,
    reconcile_deposit,
    reconciled_periods,
)
from modern_gl.desktop.bank_page.deposit_fetch import DepositFetch, reconciled_changes
from modern_gl.desktop.bank_page.deposit_reconcile_rows import ReconciledRows
from modern_gl.desktop.bank_page.portal import summary
from modern_gl.desktop.import_window import FiguresGrid, ImportWindow, say
from modern_gl.desktop.period_field import portal_period
from modern_gl.desktop.session import Session
from modern_gl.domain.dates import date_range, next_day
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import N_, tr

TITLE = N_("Сверка ƏDV depozit с порталом")


class DepositReconcileDialog(ImportWindow):
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
        super().__init__(parent, tr(TITLE), place.name)
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
        self.resize(860, 300)
        self.period_field = portal_period(self.today)
        self.period_field.changed.connect(self._period_changed)
        self.bar.addWidget(self.period_field)
        self.bar.addStretch(1)
        self.history = QLabel()
        self.history.setWordWrap(True)
        self.root.addWidget(self.history)
        self.add_notes()
        say(
            self.status,
            tr(
                "Выберите период и нажмите «Сверить с порталом»: операции портала "
                "сравниваются с выпиской счёта."
            ),
        )
        # the answer first (Jon Moon): the figures by both sides, then the operations
        self.figures = FiguresGrid([tr("На начало"), tr("Приход"), tr("Расход"), tr("На конец")])
        self.root.addWidget(self.figures)
        self.rows = ReconciledRows()
        self.rows.document_chosen.connect(self._open_document)
        self.root.addWidget(self.rows, 1)
        self.spacer = QWidget()  # the air under the period while there are no rows
        self.root.addWidget(self.spacer, 1)
        self.load_missing = self.quiet(tr("Загрузить недостающие"), self.load_missing_operations)
        self.reconcile_button = self.primary(tr("Сверить с порталом"), self.reconcile)
        self.mark_button = self.primary(tr("Отметить сверенным"), self.mark)
        self.add_footer()
        self._suggest_period()
        self._show_history()
        self._show(None)

    def _suggest_period(self) -> None:
        """From the day after the last period reconciled up to today; none — this month."""
        periods = reconciled_periods(self.s.conn, self.s.company_id, self.place)
        if periods:
            following = date.fromisoformat(next_day(periods[-1].date_to))
            if following <= self.today:
                self.period_field.set_period(following, self.today)

    def period(self) -> tuple[date, date]:
        return self.period_field.period()

    def _show_history(self) -> None:
        """The periods reconciled, and what changed in the books (on the portal — once it
        is read) since."""
        conn, cid = self.s.conn, self.s.company_id
        periods = reconciled_periods(conn, cid, self.place)
        texts = []
        if periods:
            names = (date_range(p.date_from, p.date_to, "–") for p in periods)
            texts.append(tr("Сверено с порталом: {periods}.", periods=", ".join(names)))
        changes = reconciled_changes(self.s, self.place, self.fetched)
        texts += [f"{text}." for text in changes]
        say(self.history, " ".join(texts), "warning" if changes else "secondary")

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
        problems = sum(1 for row in seen.rows if row.state != SAME)
        heading = (
            tr("✓  Период совпадает с порталом")
            if seen.agreed
            else tr("Требуют внимания: {n}", n=problems)
            if problems
            else tr("Итоги не совпадают")
        )
        self.figures.show_figures(heading, seen.agreed, figures(seen.portal), figures(seen.books))
        say(self.status, f"{verdict(seen)} {tr('Двойной щелчок по строке — открыть документ.')}")

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
                period=date_range(*self.period(), "–"),
            )
        )

    def _open_document(self, document_id: int) -> None:
        self.chosen_document = document_id
        self.accept()


def figures(f: Figures) -> list[int]:
    return [f.opening, f.money_in, f.money_out, f.closing]


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
