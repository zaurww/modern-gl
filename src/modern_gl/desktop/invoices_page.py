"""E-qaimələr: the postings of the period gathered by e-qaimə number (imported goods:
by the number of the customs declaration, shown with its own basis).

One row per invoice: its counterparty (with VÖEN) and contract, the turnovers of the
settlement accounts, the ƏDV and what is left unpaid. A number used with two
counterparties is shown in red: one of them was probably typed wrong. The search finds
an invoice by its number, the counterparty or its VÖEN; Enter opens its document.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QLineEdit

from modern_gl.application.invoices import InvoiceRow
from modern_gl.desktop.reports_page import Column, MenuAction, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, balance_text
from modern_gl.domain.dates import ru_date
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.invoices import invoice_report


def kind_name(r: InvoiceRow) -> str:
    return tr("декларация") if r.kind == CUSTOMS else "e-qaimə"


class InvoicesPage(ReportPage):
    key = ("invoices",)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("E-qaimələr"), params)
        self.open_only = QCheckBox(tr("Только неоплаченные"))
        self.open_only.setToolTip(tr("Все e-qaimə с остатком на конец периода, любой даты"))
        self.open_only.toggled.connect(self.refresh)
        self.header.add_action(self.open_only)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Номер, контрагент или VÖEN"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        self.header.add_action(self.search)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Нет e-qaimə"),
            tr("Номер e-qaimə пишется в колонке «E-qaimə» строк по счетам 60, 62 и ƏDV."),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("E-qaimələr")

    def on_postings_changed(self, doc_id: int) -> None:
        self.refresh()

    def job(self) -> Callable[[Connection], list[InvoiceRow]]:
        p, cid, open_only = self.params, self.s.company_id, self.open_only.isChecked()
        return lambda conn: invoice_report(conn, cid, p.date_from, p.date_to, p.layers, open_only)

    def fetch(self, conn: Connection) -> list[InvoiceRow]:
        return self.job()(conn)

    def present(self, data: list[InvoiceRow]) -> None:
        rows = data
        needle = fold(self.search.text().strip())
        if needle:
            rows = [r for r in rows if needle in fold(self._searched(r))]
        columns = [
            Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
            Column(tr("E-qaimə"), lambda r: r.invoice, width=170),
            Column(tr("Контрагент"), self._partners, warn=self._mixed),
            Column(tr("VÖEN"), self._tax_id, width=120, optional=True),
            Column(tr("Договор"), self._contract, width=180),
            Column(tr("Дебет"), lambda r: r.debit, money=True, width=120),
            Column(tr("Кредит"), lambda r: r.credit, money=True, width=120),
            Column(tr("ƏDV"), lambda r: r.vat, money=True, width=110),
            Column(tr("Остаток"), self._balance, width=140, right=True),
        ]
        if any(r.kind == CUSTOMS for r in rows):  # imports: customs declarations too
            columns[1] = Column(tr("Номер"), lambda r: r.invoice, width=170)
            columns.insert(1, Column(tr("Основание"), kind_name, width=110))
        self.model.set(columns, rows)
        unpaid = [r for r in rows if r.balance]
        text = tr("{n} e-qaimə", n=len(rows))
        if unpaid:
            text += "   ·   " + tr("не закрыто {n}", n=len(unpaid))
        vat = sum(r.vat for r in rows)
        if vat:
            text += "   ·   " + tr("ƏDV {amount}", amount=format_minor(vat))
        mixed = sum(1 for r in rows if len(r.counterparties) > 1)
        if mixed:
            text += "   ·   " + tr("у {n} номер с разными контрагентами", n=mixed)
        self.footer.setText(text)

    # ---- cells -----------------------------------------------------------------------

    def _name(self, value_id: int | None) -> str:
        return self.s.catalog.value(value_id).name if value_id else ""

    def _partners(self, r: InvoiceRow) -> str:
        return ", ".join(self._name(v) for v in r.counterparties)

    @staticmethod
    def _mixed(r: InvoiceRow) -> str | None:
        if len(r.counterparties) > 1:
            return tr("Один номер e-qaimə у разных контрагентов — проверьте")
        return None

    def _tax_id(self, r: InvoiceRow) -> str:
        if r.counterparty_id is None:
            return ""
        return self.s.catalog.value(r.counterparty_id).tax_id or ""

    def _contract(self, r: InvoiceRow) -> str:
        return self._name(r.contract_id)

    @staticmethod
    def _balance(r: InvoiceRow) -> str:
        return balance_text(r.balance) if r.balance else ""

    def _searched(self, r: InvoiceRow) -> str:
        parts = (r.invoice, kind_name(r), self._partners(r), self._tax_id(r), self._contract(r))
        return " ".join(parts)

    # ---- drill -----------------------------------------------------------------------

    def drill(self, row: InvoiceRow | None) -> None:
        if row is not None and row.documents:
            self.open_document.emit(row.documents[0][0])

    def menu_actions(self, row: InvoiceRow | None) -> list[MenuAction | None]:
        if row is None:
            return []
        return [
            (
                tr("Открыть документ №{n}", n=number),
                lambda doc_id=doc_id: self.open_document.emit(doc_id),
            )
            for doc_id, number in row.documents
        ]
