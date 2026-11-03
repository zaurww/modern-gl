"""«Проводки для Excel»: the postings of the period as one flat list, and the one blue
button that saves them for a pivot table (`reporting/flat_excel`: «Проводки» and
«Стороны» with the balances before the period). The page shows the list plainly — date,
document, Dt, Kt, subconto, amount — and checks it against the ОСВ; the file carries
every column. A double click opens the document."""

from __future__ import annotations

from modern_gl.desktop.reports_page.export import page_about, save_tables
from modern_gl.desktop.reports_page.view import Column, MenuItem, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.flat_excel import flat_tables
from modern_gl.reporting.flat_postings import FlatLine, FlatPostings, Side, flat_postings
from modern_gl.reporting.reports import trial_balance


def subconto_text(side: Side) -> str:
    return ", ".join(v.name for v in side.values.values())


def account_text(side: Side) -> str:
    return side.code or side.name


class FlatPostingsPage(ReportPage):
    key = ("flat_postings",)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Проводки для Excel"), params)
        self.data: FlatPostings | None = None
        self.osv_total = 0
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Проводок за период нет"),
            tr("Файл для сводной таблицы собирается из проведённых документов периода."),
        )
        self.stack.addWidget(self.empty)
        self.save_button = self.header.primary(
            tr("В Excel"),
            self.save_excel,
            tr("Плоская таблица для сводной: проводки, стороны с остатками"),
        )
        self.refresh()

    def title(self) -> str:
        return tr("Проводки для Excel")

    def more_items(self) -> list[MenuItem]:
        """The blue button is the way to Excel; «⋯» keeps the columns and the clipboard."""
        return [item for item in super().more_items() if item is None or "Excel…" not in item[0]]

    def fetch(self, conn: Connection) -> tuple[FlatPostings, int]:
        p = self.params
        flat = flat_postings(conn, self.s.company_id, p.date_from, p.date_to, p.layers)
        osv = trial_balance(conn, self.s.company_id, p.date_from, p.date_to, p.layers)
        return flat, osv.total.turnover_dt

    def present(self, data: tuple[FlatPostings, int]) -> None:
        self.data, self.osv_total = data
        columns = [
            Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
            Column(tr("№"), lambda r: str(r.number), width=60, right=True),
            Column(tr("Документ"), lambda r: r.source, width=120),
            Column(tr("Дт"), lambda r: account_text(r.debit), width=80),
            Column(tr("Субконто Дт"), lambda r: subconto_text(r.debit)),
            Column(tr("Кт"), lambda r: account_text(r.credit), width=80),
            Column(tr("Субконто Кт"), lambda r: subconto_text(r.credit)),
            Column(tr("Сумма"), lambda r: r.amount, money=True),
            Column(tr("Содержание"), lambda r: r.memo),
            Column(tr("Книга"), lambda r: r.layer, optional=True),
            Column("E-qaimə", lambda r: r.invoice, optional=True),
            Column(tr("Провёл"), lambda r: r.author, optional=True),
        ]
        self.model.set(columns, self.data.lines)
        self.footer.setText(self._check(self.data))
        self.save_button.setEnabled(bool(self.data.lines))

    def _check(self, flat: FlatPostings) -> str:
        if not flat.lines:
            return ""
        total = money(flat.total, blank_zero=False)
        count = tr("Проводок: {n}", n=len(flat.lines))
        if flat.total == self.osv_total:
            return tr(
                "{count}   ·   Дт = Кт = {total} ✓ совпадает с оборотом ОСВ",
                count=count,
                total=total,
            )
        return tr(
            "{count}   ·   Дт = Кт = {total}, оборот ОСВ {osv} — расходятся",
            count=count,
            total=total,
            osv=money(self.osv_total, blank_zero=False),
        )

    def drill(self, row: FlatLine) -> None:
        self.open_document.emit(row.document_id)

    def save_excel(self) -> None:
        """The file: «Проводки», «Стороны», «Параметры» (D104 rules, flat)."""
        if self.data is None or not self.data.lines:
            return
        tables = flat_tables(self.data, page_about(self))
        save_tables(self, tables[0], tables[1:], self.title())
