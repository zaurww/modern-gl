"""«ƏDV продаж к уплате»: the ƏDV the sales of the period owe, on the day money came from
the buyer or the e-qaimə changed the share (`reporting/vat_liability`). A double click
opens nothing: a row is many documents; the e-qaimə is in «Реестр e-qaimə»."""

from __future__ import annotations

from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.vat_payer import payer_note
from modern_gl.desktop.widgets import EmptyState, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat_liability import LiabilityRow, VatLiability, vat_liability


def invoice_text(row: LiabilityRow) -> str:
    return row.invoice if row.invoice is not None else tr("аванс")


class VatLiabilityPage(ReportPage):
    key = ("vat_liability",)
    has_book = False  # the facts are the common book's

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("ƏDV продаж к уплате"), params)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Поступлений от покупателей за период нет"),
            tr(
                "ƏDV продажи возникает в день поступления денег, аванс тоже: большее из "
                "ƏDV, пришедшего на депозитный счёт, и ƏDV поступившей стоимости."
            ),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("ƏDV продаж к уплате")

    def fetch(self, conn: Connection) -> VatLiability:
        return vat_liability(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def present(self, data: VatLiability) -> None:
        columns = [
            Column(tr("Дата"), lambda r: ru_date(r.day), width=100),
            Column(tr("E-qaimə"), invoice_text, width=140),
            Column(tr("Контрагент"), lambda r: r.counterparty),
            Column(tr("Поступило на счёт"), lambda r: r.main, money=True),
            Column(tr("Поступило на депозит ƏDV"), lambda r: r.vat, money=True),
            Column(tr("ƏDV к уплате"), lambda r: r.owed, money=True),
        ]
        self.model.set(columns, data.rows)
        text = tr("ƏDV продаж за период: {owed}", owed=money(data.owed, blank_zero=False))
        note = payer_note(data.payer_from, self.params.date_from)
        self.footer.setText(f"{text}\n{note}" if note else text)
