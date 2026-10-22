"""Сравнение книг (D98): the common, IFRS and tax books side by side on a day; by default
only the accounts where they differ. A double click opens the account's card."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout

from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    EmptyState,
    balance_text,
    button,
    date_edit,
    edited_date,
    ru_date,
)
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.books import BookRow, compare_books


def difference(net: int) -> str:
    return balance_text(net) if net else ""


class BooksPage(ReportPage):
    key = ("books",)
    has_period = False  # one day: the balances on it

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Сравнение книг"), params)
        self.only = QCheckBox(tr("Только расхождения"))
        self.only.setToolTip(tr("Скрыть счета, где все три книги совпадают"))
        self.only.setChecked(True)
        self.only.toggled.connect(self.refresh)
        self.header.add_action(self.only)
        self.stack.removeWidget(self.empty)  # nothing found means the books agree
        self.empty = EmptyState(
            "○", tr("Книги совпадают"), tr("На эту дату корректировок МСФО и налога нет.")
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Сравнение книг")

    def _build_period_bar(self, root: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        label = QLabel(tr("На дату"))
        label.setObjectName("secondary")
        self.day = date_edit(self.params.date_to)
        self.day.setFixedWidth(130)
        run = button(tr("Сформировать"), "primary", "F5")
        run.clicked.connect(self.refresh)
        for w in (label, self.day, run):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

    def refresh(self) -> None:
        day = edited_date(self.day)
        self.params = ReportParams(self.params.date_from, day)
        self.header.subtitle.setText(
            tr("Сальдо на {day}: общая книга, МСФО и налог", day=ru_date(iso_date(day)))
        )
        super().refresh()

    def job(self):
        cid, day, only = self.s.company_id, self.params.date_to, self.only.isChecked()
        return lambda conn: compare_books(conn, cid, day, only)

    def fetch(self, conn: Connection) -> list[BookRow]:
        return compare_books(conn, self.s.company_id, self.params.date_to, self.only.isChecked())

    def present(self, data: list[BookRow]) -> None:
        indent = "      "
        columns = [
            Column(tr("Счёт"), lambda r: indent * r.depth + r.code, width=90),
            Column(tr("Наименование"), lambda r: r.name),
            Column(tr("Общий учёт"), lambda r: balance_text(r.common), right=True),
            Column(tr("Книга"), lambda r: balance_text(r.ifrs), right=True, group=tr("МСФО")),
            Column(tr("Разница"), lambda r: difference(r.ifrs_adj), right=True, group=tr("МСФО")),
            Column(
                tr("Книга"), lambda r: balance_text(r.tax), right=True, group=tr("Налоговый учёт")
            ),
            Column(
                tr("Разница"),
                lambda r: difference(r.tax_adj),
                right=True,
                group=tr("Налоговый учёт"),
            ),
        ]
        self.model.set(columns, data, emphasis=lambda r: r.is_group, muted=lambda r: r.depth > 0)
        differ = [r for r in data if r.differs and not r.is_group]
        self.footer.setText(
            tr("Книги совпадают  ✓")
            if not differ
            else tr("Расхождения по счетам: {n}", n=len(differ))
        )

    def drill(self, row: BookRow) -> None:
        if row and row.account_id:
            self.open_report.emit("card", row.account_id, self.params)
