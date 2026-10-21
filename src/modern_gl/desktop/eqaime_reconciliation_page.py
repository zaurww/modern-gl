"""«Сверка с порталом»: the e-qaimə of a month on the tax portal against the books (D53) —
what is forgotten, cancelled, different; the totals on top; the month marked reconciled."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.eqaime_portal import (
    fetch_list,
    full_month,
    month_bounds,
    read_again,
    rechecks,
)
from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog, PortalLoader, changes_warning
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import button, date_edit, edited_date, money
from modern_gl.domain.dates import month_name, ru_date
from modern_gl.domain.eqaime import ON_APPROVAL, PortalInvoice, status_label
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
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
    reconcile,
    reconciled_months,
)

COLUMNS = ["Дата", "E-qaimə", "Контрагент", "На портале", "Портал", "Книга", "Разница", ""]
GROUP_TITLES = {
    MISSING: "Есть на портале, нет в книге",
    VOID_IN_BOOKS: "В книге, но на портале не действует",
    NOT_ON_PORTAL: "В книге, на портале не найдена",
    AMOUNTS: "Суммы различаются",
    PERIOD: "Другой период",
    PARTY: "Другой контрагент",
    PENDING: "Ожидает подтверждения или в процессе",
    MATCHED: "Совпадает",
}
AMOUNT_COLUMNS = (4, 5, 6)


@dataclass
class PortalLists:
    listed: list[PortalInvoice]  # the period, every status
    rechecked: list[PortalInvoice]  # the reconciled months read again


class EqaimeReconciliationDialog(QDialog):
    """Period → sign in → the portal's list in every status → the books against it."""

    def __init__(
        self,
        session: Session,
        parent: QWidget | None = None,
        sign_in: Callable[[QWidget], str | None] | None = None,
        direction: str = "receipt",  # "receipt" (purchases) or "sale"
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.sign_in = sign_in
        self.outgoing = direction == "sale"
        self.token: str | None = None
        self.outcome: Reconciliation | None = None
        self.chosen_document: int | None = None  # double-clicked: the caller opens it
        self.period = (session.working_date, session.working_date)  # of the last load
        self.worker: QThread | None = None
        title_text = tr(
            "Сверка продаж с порталом" if self.outgoing else "Сверка покупок с порталом"
        )
        self.setWindowTitle(title_text)
        self.resize(1180, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)

        title = QLabel(title_text)
        title.setFont(fonts().title)
        root.addWidget(title)
        self.company = QLabel(
            tr("Все e-qaimə периода с портала против проведённых документов с их номерами")
        )
        self.company.setObjectName("secondary")
        root.addWidget(self.company)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        first, last = month_bounds(f"{session.working_date:%Y-%m}")
        self.date_from = date_edit(first)
        self.date_to = date_edit(last)
        for caption, widget in ((tr("Период с"), self.date_from), (tr("по"), self.date_to)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            widget.setFixedWidth(130)
            bar.addWidget(label)
            bar.addWidget(widget)
        bar.addSpacing(10)
        self.load_button = button(tr("Сверить с порталом"), "primary")
        self.load_button.clicked.connect(self.load)
        bar.addWidget(self.load_button)
        bar.addStretch(1)
        root.addLayout(bar)

        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        root.addWidget(self.warning)

        # the answer first (Jon Moon): does the period agree, and the totals
        self.verdict = QLabel()
        self.verdict.setFont(fonts().heading)
        root.addWidget(self.verdict)
        totals = QGridLayout()
        totals.setHorizontalSpacing(28)
        totals.setVerticalSpacing(4)
        self.totals: dict[tuple[int, int], QLabel] = {}
        for column, caption in enumerate((tr("Без ƏDV"), tr("ƏDV"), tr("Итого")), 1):
            head = QLabel(caption)
            head.setObjectName("secondary")
            head.setAlignment(Qt.AlignmentFlag.AlignRight)
            totals.addWidget(head, 0, column)
        for row, caption in enumerate((tr("Портал"), tr("Книга"), tr("Разница")), 1):
            label = QLabel(caption)
            label.setObjectName("secondary")
            totals.addWidget(label, row, 0)
            for column in (1, 2, 3):
                cell = QLabel()
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                cell.setMinimumWidth(110)
                totals.addWidget(cell, row, column)
                self.totals[row, column] = cell
        totals.setColumnStretch(4, 1)
        self.totals_box = QWidget()
        self.totals_box.setLayout(totals)
        self.totals_box.hide()
        root.addWidget(self.totals_box)

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
        root.addWidget(self.tree, 1)

        self.status = QLabel(
            tr(
                "Выберите месяц и нажмите «Сверить с порталом»: откроется вход через ASAN İmza. "
                "Программа сравнит e-qaimə портала с проведёнными документами по номеру."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        self.import_button = button(tr("Загрузить недостающие…"), "flat")
        self.import_button.setToolTip(tr("Черновики из e-qaimə, которых нет в книге"))
        self.import_button.clicked.connect(self.import_missing)
        self.import_button.hide()
        actions.addWidget(self.import_button)
        actions.addStretch(1)
        close = button(tr("Закрыть"), "flat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.mark_button = button(tr("Месяц сверен"), "primary")
        self.mark_button.clicked.connect(self.toggle_reconciled)
        self.mark_button.setEnabled(False)
        actions.addWidget(self.mark_button)
        root.addLayout(actions)

    # ---- loading -------------------------------------------------------------------

    def _signed_in(self) -> str | None:
        from modern_gl.desktop import portal_login

        token = self.token
        if token is None or not portal_login.token_alive(token):
            sign_in = self.sign_in or portal_login.sign_in
            token = sign_in(self)
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
        date_from, date_to = edited_date(self.date_from), edited_date(self.date_to)
        outgoing = self.outgoing
        checks = rechecks(self.s.conn, self.s.company_id, date.today())
        self.period = (date_from, date_to)
        self.load_button.setEnabled(False)
        self.status.setText(tr("Загрузка с портала…"))
        self.worker = QThread(self)
        self.loader = PortalLoader(
            lambda progress: PortalLists(
                fetch_list(client, outgoing, date_from, date_to, progress),
                read_again(client, checks, progress),
            )
        )
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.progress.connect(self.status.setText)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()

    def _failed(self, message: str) -> None:
        self.load_button.setEnabled(True)
        self.status.setText(message)
        self.token = None

    def _loaded(self, lists: PortalLists) -> None:
        self.load_button.setEnabled(True)
        try:
            self.s.ledger.remember_portal(self.s.company_id, [*lists.rechecked, *lists.listed])
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        warning = changes_warning(self.s.conn, self.s.company_id)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.show_result(
            reconcile(self.s.conn, self.s.company_id, self.outgoing, *self.period, lists.listed)
        )

    # ---- the result ----------------------------------------------------------------

    def show_result(self, result: Reconciliation) -> None:
        self.outcome = result
        if result.agrees:
            self.verdict.setText(tr("✓  Период совпадает с порталом"))
            self.verdict.setStyleSheet(f"color: {P.green};")
        else:
            self.verdict.setText(
                tr("Требуют внимания: {n}", n=result.problems)
                if result.problems
                else tr("Итоги не совпадают")
            )
            self.verdict.setStyleSheet(f"color: {P.text};")
        figures = (
            (result.portal_total - result.portal_vat, result.portal_vat, result.portal_total),
            (result.book_total - result.book_vat, result.book_vat, result.book_total),
        )
        for row, values in enumerate(figures, 1):
            for column, value in enumerate(values, 1):
                self.totals[row, column].setText(format_minor(value))
        for column in (1, 2, 3):
            difference = figures[0][column - 1] - figures[1][column - 1]
            cell = self.totals[3, column]
            cell.setText(_signed(difference))
            cell.setStyleSheet(f"color: {P.red if difference else P.secondary};")
        self.totals_box.show()

        self.tree.clear()
        for group in GROUP_TITLES:
            rows = result.group(group)
            if not rows:
                continue
            head = QTreeWidgetItem([f"{tr(GROUP_TITLES[group])}  {len(rows)}"])
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
                _signed(row.difference) if row.difference else "",
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
            notes.append(tr("в т.ч. ƏDV {amount}", amount=_signed(row.vat_difference)))
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

    # ---- the month -----------------------------------------------------------------

    def _month(self) -> str | None:
        if self.outcome is None:
            return None
        return full_month(
            date.fromisoformat(self.outcome.date_from), date.fromisoformat(self.outcome.date_to)
        )

    def _show_mark(self) -> None:
        month = self._month()
        marked = reconciled_months(self.s.conn, self.s.company_id, self.outgoing)
        self.mark_button.setEnabled(month is not None)
        if month is None:
            self.mark_button.setText(tr("Месяц сверен"))
            self.mark_button.setToolTip(tr("Отметить можно только целый месяц"))
        elif month in marked:
            self.mark_button.setText(tr("Снять отметку «сверен»"))
            self.mark_button.setObjectName("flat")
            self.mark_button.setToolTip(tr("Сверен {date}", date=ru_date(marked[month][:10])))
        else:
            self.mark_button.setText(tr("{month} сверен", month=month_name(month).capitalize()))
            self.mark_button.setObjectName("primary")
            self.mark_button.setToolTip(
                tr("Если потом на портале что-то изменится, программа предупредит")
            )
        self.mark_button.style().unpolish(self.mark_button)
        self.mark_button.style().polish(self.mark_button)

    def toggle_reconciled(self) -> None:
        month = self._month()
        if month is None:
            return
        try:
            if month in reconciled_months(self.s.conn, self.s.company_id, self.outgoing):
                self.s.ledger.unmark_reconciled(self.s.company_id, self.outgoing, month)
            else:
                self.s.ledger.mark_reconciled(self.s.company_id, self.outgoing, month)
                self.s.notify(tr("{month}: отмечен сверенным", month=month_name(month)))
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self._show_mark()

    def import_missing(self) -> None:
        """The import of the same period and direction, signed in already."""
        if self.outcome is None:
            return
        dialog = EqaimeImportDialog(
            self.s, self, sign_in=self.sign_in, direction="sale" if self.outgoing else "receipt"
        )
        dialog.token = self.token
        dialog.date_from.setDate(self.date_from.date())
        dialog.date_to.setDate(self.date_to.date())
        if dialog.exec() and dialog.created:
            self.s.notify(
                tr("Создано черновиков: {n} — проверьте и проведите", n=len(dialog.created))
            )


def _signed(minor: int) -> str:
    """A difference: negative in brackets, as the reports show it (D52)."""
    return f"({format_minor(-minor)})" if minor < 0 else format_minor(minor)
