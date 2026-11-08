"""Карточка субконто (D126): the postings of one element across every account, or on one
account — opened from «Анализ субконто» by a double click; a line leads to its document."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.posting_preview import PreviewPosting, gl_postings
from modern_gl.desktop.reports_page.account import document_text, invoice_text
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import balance_text, ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.report_common import SubcontoCardLine


@dataclass
class Edge:
    """The first and last rows of the card: the balances, and the turnovers at the end."""

    memo: str
    balance: int
    debit: int | None = None
    credit: int | None = None
    doc_date: str = ""
    number: int = 0
    document_id: int = 0
    debit_code: str = ""
    credit_code: str = ""
    invoice: str = ""
    invoice_kind: str = ""


class SubcontoCardPage(ReportPage):
    """`account_id` 0 — every account the element is on; else that one account.
    `params.subconto[0]` — the element."""

    def __init__(self, session: Session, account_id: int, params: ReportParams) -> None:
        value_id = params.subconto[0]
        assert value_id is not None
        self.value_id: int = value_id
        self.account_id = account_id or None
        super().__init__(session, "", params)
        self.header.title.setText(self.title())
        self.key = ("subconto_card", self.value_id, account_id)
        self.refresh()

    def title(self) -> str:
        value = self.s.catalog.value(self.value_id)
        title = f"{tr('Карточка субконто')} · {value.name}"
        if self.account_id is not None:
            title += f" · {self.s.catalog.accounts[self.account_id].short}"
        return title

    def refresh(self) -> None:
        super().refresh()
        value = self.s.catalog.value(self.value_id)
        parts = [self.s.catalog.kinds[value.kind_id]]
        if self.account_id is not None:
            parts.append(self.s.catalog.accounts[self.account_id].name)
        parts.append(self.params.describe(self.s.parallel_books))
        self.header.subtitle.setText("   ·   ".join(parts))

    def fetch(self, conn: Connection) -> reports.SubcontoCard:
        p, cid = self.params, self.s.company_id
        return reports.subconto_card(
            conn, cid, self.value_id, p.date_from, p.date_to, p.layers, self.account_id
        )

    def present(self, data: reports.SubcontoCard) -> None:
        card = data
        one_year = self.params.date_from.year == self.params.date_to.year
        columns = [
            Column(tr("Дата"), lambda ln: self._date(ln.doc_date, one_year), width=1),
            Column(tr("Документ"), document_text, width=1),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Дт"), lambda ln: ln.debit_code, width=1, group=tr("Счета")),
            Column(tr("Кт"), lambda ln: ln.credit_code, width=1, group=tr("Счета")),
            Column(tr("Дт"), lambda ln: ln.debit, money=True, group=tr("Обороты")),
            Column(tr("Кт"), lambda ln: ln.credit, money=True, group=tr("Обороты")),
            Column(
                tr("Сальдо"),
                lambda ln: balance_text(ln.balance) if ln.balance else "",
                right=True,
                value=lambda ln: ln.balance,  # in Excel: Dt +, Kt −
            ),
        ]
        if any(ln.invoice for ln in card.lines):
            columns.insert(3, Column(tr("E-qaimə"), invoice_text, width=1))
        opening = Edge(tr("Сальдо на начало"), card.opening)
        closing = Edge(
            tr("Обороты и сальдо на конец"),
            card.closing,
            sum(ln.debit for ln in card.lines),
            sum(ln.credit for ln in card.lines),
        )
        self.model.set(
            columns,
            [opening, *card.lines, closing] if card.lines else [],
            emphasis=lambda ln: ln is closing,
            muted=lambda ln: ln is opening,
            total=lambda ln: ln is closing,
        )
        self.footer.setText(
            tr(
                "Сальдо на начало: {start}      Сальдо на конец: {end}",
                start=balance_text(card.opening),
                end=balance_text(card.closing),
            )
        )

    @staticmethod
    def _date(iso: str, one_year: bool) -> str:
        text = ru_date(iso) if iso else ""
        return text[:5] if one_year else text

    def drill(self, row) -> None:
        if row is not None and row.document_id:
            self.open_document.emit(row.document_id)

    def row_postings(self) -> list[PreviewPosting] | None:
        row = self.current_row()
        if not isinstance(row, SubcontoCardLine):
            return None
        return gl_postings(self.s.conn, self.s.company_id, row.document_id)
