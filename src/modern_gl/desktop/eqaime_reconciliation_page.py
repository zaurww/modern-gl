"""«Сверка с порталом»: the e-qaimə of a period on the tax portal against the books (D53) —
what is forgotten, cancelled, different; the totals on top; the period marked reconciled.
Made for a morning check too: «Вчера», «Эта неделя», «Прошлый месяц»… set the period at
a click (`period_field.portal_period`); a morning check looks at finished days — the
period ends yesterday."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from modern_gl.application.eqaime.portal import fetch_list, read_again, rechecks, usual_span
from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
from modern_gl.desktop.eqaime_portal_loader import changes_warning
from modern_gl.desktop.import_window import FiguresGrid, ImportWindow, restyle, say, signed
from modern_gl.desktop.period_field import portal_period
from modern_gl.desktop.portal_worker import PortalRun, run_on_portal
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import money
from modern_gl.domain.dates import date_range, month_name, ru_date
from modern_gl.domain.eqaime import ON_APPROVAL, PortalInvoice, status_label
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.domain.periods import full_month
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.etaxes import EtaxesClient
from modern_gl.reporting.eqaime_reconciliation import (
    AMOUNTS,
    MATCHED,
    MISSING,
    NOT_ON_PORTAL,
    PARTY,
    PENDING,
    PERIOD,
    PROBLEMS,
    VOID_IN_BOOKS,
    Reconciliation,
    ReconciliationRow,
    books_changed,
    reconcile,
    reconciled_periods,
    reconciled_through,
)

COLUMNS = [
    N_("Дата"),
    N_("E-qaimə"),
    N_("Контрагент"),
    N_("На портале"),
    N_("Портал"),
    N_("Книга"),
    N_("Разница"),
    "",
]
GROUP_TITLES = {
    MISSING: N_("Есть на портале, нет в книге"),
    VOID_IN_BOOKS: N_("В книге, но на портале не действует"),
    NOT_ON_PORTAL: N_("В книге, на портале не найдена"),
    AMOUNTS: N_("Суммы различаются"),
    PERIOD: N_("Другой период"),
    PARTY: N_("Другой контрагент"),
    PENDING: N_("Ожидает подтверждения или в процессе"),
    MATCHED: N_("Совпадает"),
}
AMOUNT_COLUMNS = (4, 5, 6)


@dataclass
class PortalLists:
    listed: list[PortalInvoice]  # the period, every status
    skipped: list[str]  # statuses the portal refused to filter by
    rechecked: list[PortalInvoice]  # the reconciled months read again


class EqaimeReconciliationDialog(ImportWindow):
    """Period → sign in → the portal's list in every status → the books against it."""

    def __init__(
        self,
        session: Session,
        parent: QWidget | None = None,
        sign_in: Callable[[QWidget], str | None] | None = None,
        direction: str = "receipt",  # "receipt" (purchases) or "sale"
        today: date | None = None,
    ) -> None:
        outgoing = direction == "sale"
        title_text = tr("Сверка продаж с порталом" if outgoing else "Сверка покупок с порталом")
        super().__init__(
            parent,
            title_text,
            tr("Все e-qaimə периода с портала против проведённых документов с их номерами"),
        )
        self.s = session
        self.sign_in = sign_in
        self.outgoing = direction == "sale"
        self.token: str | None = None
        self.outcome: Reconciliation | None = None
        self.chosen_document: int | None = None  # double-clicked: the caller opens it
        self.period = (session.working_date, session.working_date)  # of the last load
        self.portal_run: PortalRun | None = None
        self.today = today or date.today()
        self.company = self.subtitle
        self.through = self.subtitle_note  # «Сверено по 20.10.2026»
        self.resize(1180, 760)
        # the usual period at a click: the one this company was last marked with
        self.period_field = portal_period(
            self.today,
            usual_span(self.s.conn, self.s.company_id, self.outgoing),
            last=self.today - timedelta(days=1),
        )
        self.period_field.changed.connect(self._period_changed)
        self.bar.addWidget(self.period_field)
        self.bar.addStretch(1)
        self._show_through()
        self.add_notes()
        say(
            self.status,
            tr(
                "Выберите период и нажмите «Сверить с порталом»: откроется вход через ASAN "
                "İmza. Программа сравнит e-qaimə портала с проведёнными документами по номеру."
            ),
        )
        # the answer first (Jon Moon): does the period agree, and the totals
        self.figures = FiguresGrid([tr("Без ƏDV"), tr("ƏDV"), tr("Итого")])
        self.verdict, self.totals = self.figures.verdict, self.figures.cells
        self.figures.hide()
        self.root.addWidget(self.figures)
        self._build_tree()
        self._build_actions()

    def _build_tree(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels([tr(c) for c in COLUMNS])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        # widths by content; what is wrong takes the rest, no horizontal scrolling
        for column, width in enumerate((120, 140, 220, 170, 100, 100, 100)):
            self.tree.setColumnWidth(column, width)
        self.tree.header().setStretchLastSection(True)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        for column in AMOUNT_COLUMNS:
            self.tree.headerItem().setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.hide()
        self.spacer = QWidget()  # the air under the period while there are no rows
        self.root.addWidget(self.tree, 1)
        self.root.addWidget(self.spacer, 1)

    def _build_actions(self) -> None:
        self.import_button = self.quiet(tr("Загрузить недостающие…"), self.import_missing)
        self.import_button.setToolTip(tr("Черновики из e-qaimə, которых нет в книге"))
        self.import_button.hide()
        self.load_button = self.primary(tr("Сверить с порталом"), self.load)
        self.mark_button = self.primary(tr("Сверено"), self.toggle_reconciled)
        self.mark_button.hide()
        self.add_footer()

    def _period_changed(self) -> None:
        """The rows were of another period: back to the first step."""
        if self.outcome is None:
            return
        self.outcome = None
        self.figures.hide()
        self.tree.clear()
        self.tree.hide()
        self.spacer.show()
        self.import_button.hide()
        self.mark_button.hide()
        self.load_button.show()
        say(self.status, tr("Период изменён — сверьте его с порталом."))

    # ---- loading -------------------------------------------------------------------

    def _signed_in(self) -> str | None:
        from modern_gl.desktop import portal_login
        from modern_gl.desktop.portal_company import company_token

        token = company_token(self, self.s, self.sign_in)  # this company's, D113
        if not token:
            return None
        self.token = token
        name, tin = portal_login.company_name(token), portal_login.company_tin(token)
        self.company.setText(tr("Портал: {name} · VÖEN {tin}", name=name, tin=tin))
        return token

    def load(self) -> None:
        token = self._signed_in()
        if token is None:
            return
        client = EtaxesClient(token)
        date_from, date_to = self.period_field.period()
        outgoing = self.outgoing
        checks = rechecks(self.s.conn, self.s.company_id, date.today())
        self.period = (date_from, date_to)
        self.load_button.setEnabled(False)
        self.status.setText(tr("Загрузка с портала…"))
        skipped: list[str] = []
        self.portal_run = run_on_portal(
            self,
            lambda progress: PortalLists(
                fetch_list(client, outgoing, date_from, date_to, progress, skipped=skipped),
                skipped,
                read_again(client, checks, progress),
            ),
            self.status.setText,
            self._loaded,
            self._failed,
        )

    def _failed(self, message: str) -> None:
        self.load_button.setEnabled(True)
        self.status.setText(message)
        self.token = None
        from modern_gl.desktop import portal_login

        portal_login.forget_token()  # a new sign-in next time

    def _loaded(self, lists: PortalLists) -> None:
        self.load_button.setEnabled(True)
        try:
            self.s.ledger.eqaime.remember_portal(
                self.s.company_id, [*lists.rechecked, *lists.listed]
            )
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        warning = changes_warning(self.s.conn, self.s.company_id)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.show_result(
            reconcile(self.s.conn, self.s.company_id, self.outgoing, *self.period, lists.listed)
        )
        if lists.skipped:
            refused = ", ".join(status_label(status) for status in lists.skipped)
            self.status.setText(
                f"{self.status.text()} "
                + tr("Портал не дал статусы: {statuses} — они не проверены.", statuses=refused)
            )

    # ---- the result ----------------------------------------------------------------

    def show_result(self, result: Reconciliation) -> None:
        self.outcome = result
        verdict = tr("✓  Период совпадает с порталом")
        if not result.agrees:
            verdict = (
                tr("Требуют внимания: {n}", n=result.problems)
                if result.problems
                else tr("Итоги не совпадают")
            )
        self.figures.show_figures(
            verdict,
            result.agrees,
            [result.portal_total - result.portal_vat, result.portal_vat, result.portal_total],
            [result.book_total - result.book_vat, result.book_vat, result.book_total],
        )
        for widget, shown in (
            (self.figures, True),
            (self.tree, True),
            (self.spacer, False),
            (self.load_button, False),
            (self.mark_button, True),
        ):
            widget.setVisible(shown)
        self.tree.clear()
        for group, title in GROUP_TITLES.items():
            rows = result.group(group)
            if not rows:
                continue
            head = QTreeWidgetItem([f"{tr(title)}  {len(rows)}"])
            head.setFirstColumnSpanned(True)
            head.setFont(0, fonts().heading)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if group in PROBLEMS:
                head.setForeground(0, QColor(P.text))
            else:
                head.setForeground(0, QColor(P.secondary))
            self.tree.addTopLevelItem(head)
            head.setFirstColumnSpanned(True)
            for row in rows:
                head.addChild(self._row_item(row))
            head.setExpanded(group != MATCHED)  # what agrees is there, but folded
        self.import_button.setVisible(bool(result.group(MISSING)))
        self._show_mark()
        self.status.setText(
            tr(
                "E-qaimə на портале: {portal}, в книге: {books}. "
                "Двойной щелчок — открыть документ.",
                portal=sum(1 for r in result.rows if r.portal is not None),
                books=sum(1 for r in result.rows if r.book is not None),
            )
        )

    def _row_item(self, row: ReconciliationRow) -> QTreeWidgetItem:
        portal, book = row.portal, row.book
        party = portal.party_name if portal and portal.party_name else self._book_party(row)
        item = QTreeWidgetItem(
            [
                ru_date(row.doc_date) if row.doc_date else "",
                row.number,
                party,
                status_label(portal.status) if portal else "",
                money(portal.total, blank_zero=False) if portal else "–",
                money(book.total, blank_zero=False) if book else "–",
                signed(row.difference) if row.difference else "",
                self._note(row),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, row)
        for column in AMOUNT_COLUMNS:
            item.setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        for column in (0, 3, 7):
            item.setForeground(column, QColor(P.secondary))
        if row.difference:
            item.setForeground(6, QColor(P.red))
        if book is not None:
            item.setToolTip(
                1,
                tr(
                    "Документы: {numbers}",
                    numbers=", ".join(f"№{number}" for _, number in book.documents),
                ),
            )
        return item

    def _book_party(self, row: ReconciliationRow) -> str:
        if row.book is None or not row.book.parties:
            return ""
        return self.s.catalog.value(row.book.parties[0]).name

    def _note(self, row: ReconciliationRow) -> str:
        """What is wrong, in a few words; and what changed on the portal since."""
        portal, book = row.portal, row.book
        notes = []
        if row.group == MISSING:
            notes.append(tr("не проведена в книге"))
        elif row.group == NOT_ON_PORTAL:
            notes.append(tr("номера нет на портале — опечатка?"))
        elif row.group == PERIOD and portal and book:
            notes.append(
                tr(
                    "на портале {portal}, в книге {book}",
                    portal=ru_date(portal.doc_date),
                    book=ru_date(book.doc_date),
                )
            )
        elif row.group == PARTY and portal:
            notes.append(tr("VÖEN на портале {tin}", tin=portal.party_tin))
        if row.group == AMOUNTS and row.vat_difference:
            notes.append(tr("в т.ч. ƏDV {amount}", amount=signed(row.vat_difference)))
        if row.group == PENDING and portal and book is None and portal.status != ON_APPROVAL:
            notes.append(tr("нет в книге"))
        for change in row.changes:
            if change.old_total != change.new_total:
                notes.append(
                    tr(
                        "на портале было {old}",
                        old=format_minor(change.old_total),
                    )
                )
            elif change.old_status != change.new_status:
                notes.append(
                    tr("на портале было: {status}", status=status_label(change.old_status))
                )
        return "; ".join(notes)

    def _open(self, item: QTreeWidgetItem, _column: int) -> None:
        row = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(row, ReconciliationRow) and row.book is not None and row.book.documents:
            self.chosen_document = row.book.documents[0][0]
            self.accept()

    # ---- the period ----------------------------------------------------------------

    def _show_through(self) -> None:
        through = reconciled_through(self.s.conn, self.s.company_id, self.outgoing)
        self.through.setText(tr("Сверено по {date}", date=ru_date(through)) if through else "")

    def _marked_period(self) -> tuple[str, str] | None:
        """The period of the shown result."""
        if self.outcome is None:
            return None
        return self.outcome.date_from, self.outcome.date_to

    def _is_marked(self, period: tuple[str, str]) -> bool:
        """Marked, and the books did not change since (D140): else it is marked again."""
        conn, cid = self.s.conn, self.s.company_id
        stale = {(m.date_from, m.date_to) for m in books_changed(conn, cid, self.outgoing)}
        return period not in stale and any(
            (m.date_from, m.date_to) == period for m in reconciled_periods(conn, cid, self.outgoing)
        )

    def _show_mark(self) -> None:
        period = self._marked_period()
        if period is None:
            return
        if self._is_marked(period):
            self.mark_button.setText(tr("Снять отметку «сверено»"))
            self.mark_button.setObjectName("flat")
            self.mark_button.setToolTip("")
        else:
            self.mark_button.setText(tr("Сверено: {period}", period=period_text(*period)))
            self.mark_button.setObjectName("primary")
            self.mark_button.setToolTip(
                tr("Если потом на портале что-то изменится, программа предупредит")
            )
        restyle(self.mark_button)

    def toggle_reconciled(self) -> None:
        period = self._marked_period()
        if period is None:
            return
        try:
            if self._is_marked(period):
                self.s.ledger.eqaime.unmark_reconciled(self.s.company_id, self.outgoing, *period)
            else:
                self.s.ledger.eqaime.mark_reconciled(self.s.company_id, self.outgoing, *period)
                self.s.notify(tr("Отмечено сверенным: {period}", period=period_text(*period)))
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self._show_mark()
        self._show_through()

    def import_missing(self) -> None:
        """The import of the same period and direction, signed in already."""
        if self.outcome is None:
            return
        dialog = EqaimeImportDialog(
            self.s, self, sign_in=self.sign_in, direction="sale" if self.outgoing else "receipt"
        )
        dialog.token = self.token
        dialog.period_field.set_period(*self.period_field.period())
        if dialog.exec() and (dialog.created or dialog.attached):
            self.s.notify(dialog.outcome())


def period_text(date_from: str, date_to: str) -> str:
    """'март 2026' for a whole month, '20.10.2026' for a day, '14.10–20.10.2026' else."""
    month = full_month(date.fromisoformat(date_from), date.fromisoformat(date_to))
    if month:
        return month_name(month)
    return date_range(date_from, date_to, "–")
