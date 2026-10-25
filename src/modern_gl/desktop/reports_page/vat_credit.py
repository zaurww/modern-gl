"""«ƏDV к зачёту»: the input ƏDV credited in the period by e-qaimə and customs
declaration, on the day the credit came, and what still waits (`reporting/vat`). A double
click opens the document of the e-qaimə."""

from __future__ import annotations

from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.vat_payer import payer_note
from modern_gl.desktop.widgets import EmptyState, money
from modern_gl.domain.dates import ru_date
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat import CreditRow, VatCredit, vat_credit


def document_text(row: CreditRow) -> str:
    return tr("ГТД {n}", n=row.invoice) if row.kind == CUSTOMS else row.invoice


class VatCreditPage(ReportPage):
    key = ("vat_credit",)
    has_book = False  # the facts are the common book's

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("ƏDV к зачёту"), params)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Зачёта за период нет"),
            tr(
                "ƏDV покупки зачитывается, когда есть e-qaimə и оплачены основная сумма с "
                "банка и ƏDV на депозитный счёт поставщика, в доле оплаченного; по "
                "таможенной декларации — по оплате ƏDV таможне."
            ),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("ƏDV к зачёту")

    def fetch(self, conn: Connection) -> VatCredit:
        return vat_credit(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def present(self, data: VatCredit) -> None:
        columns = [
            Column(tr("Дата зачёта"), lambda r: ru_date(r.day), width=100),
            Column(tr("E-qaimə / ГТД"), document_text, width=140),
            Column(tr("Контрагент"), lambda r: r.counterparty),
            Column(tr("ƏDV по документу"), lambda r: r.vat, money=True),
            Column(tr("К зачёту"), lambda r: r.credited, money=True),
            Column(tr("Зачтено ранее"), lambda r: r.before, money=True, optional=True),
            Column(tr("Ждёт"), lambda r: r.waiting, money=True),
        ]
        self.model.set(columns, data.rows)
        text = tr(
            "К зачёту за период: {credited}   ·   ждут e-qaimə или оплаты: {waiting} "
            "по {n} покупкам",
            credited=money(data.credited, blank_zero=False),
            waiting=money(data.waiting, blank_zero=False),
            n=data.waiting_count,
        )
        note = payer_note(data.payer_from, self.params.date_from)
        self.footer.setText(f"{text}\n{note}" if note else text)

    def drill(self, row) -> None:
        if row is not None and row.document_id:
            self.open_document.emit(row.document_id)
