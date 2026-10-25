"""«Поступления и e-qaimə»: each buyer's money against the e-qaimə issued to them, the
ƏDV owed, what is open at the period's end and what wants a look (`reporting/vat_receipts`).
Under a buyer — their e-qaimə and the money without a number. A double click on an
e-qaimə opens its document, on a buyer or their advance — the card of the buyer (D126),
with the statements; a number in a payment is set in the bank (D67)."""

from __future__ import annotations

import html
from dataclasses import replace

from modern_gl.desktop.reports_page.subconto_analysis import INDENT
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import EmptyState, money
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat_receipts import (
    BuyerRow,
    ReceiptLine,
    VatReceipts,
    vat_receipts,
    warning,
)


def name_text(row: ReceiptLine) -> str:
    if isinstance(row, BuyerRow):
        return row.name or tr("Без контрагента")
    if row.invoice is None:
        return INDENT + tr("аванс")
    return INDENT + row.invoice


SHOWN_WARNINGS = 3  # in the footer; the rest are counted, each is on its buyer's cell


def check_text(row: ReceiptLine) -> str | None:
    return warning(row) if isinstance(row, BuyerRow) else None


def warnings_text(data: VatReceipts) -> str:
    """«Бета — ƏDV e-qaimə пришёл…» in red, a line each, the first few."""
    found = [(b.name, text) for b in data.buyers if (text := warning(b))]
    lines = [f"{name or tr('Без контрагента')} — {text}" for name, text in found]
    if len(lines) > SHOWN_WARNINGS:
        rest = len(lines) - SHOWN_WARNINGS
        lines = [*lines[:SHOWN_WARNINGS], tr("и ещё {n}", n=rest)]
    return "".join(f'<br><span style="color: {P.red}">{html.escape(t)}</span>' for t in lines)


class VatReceiptsPage(ReportPage):
    key = ("vat_receipts",)
    has_book = False  # the facts are the common book's

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Поступления и e-qaimə"), params)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Поступлений и e-qaimə покупателям за период нет"),
            tr(
                "По каждому покупателю: деньги с номером e-qaimə и без, выписанные e-qaimə, "
                "начисленный ƏDV, аванс и неоплаченное на конец периода."
            ),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Поступления и e-qaimə")

    def fetch(self, conn: Connection) -> VatReceipts:
        return vat_receipts(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def present(self, data: VatReceipts) -> None:
        received, issued, end = tr("Поступило"), tr("E-qaimə"), tr("На конец периода")

        def balance(name: str):
            return lambda r: getattr(r, name) if isinstance(r, BuyerRow) else None

        columns = [
            Column(tr("Покупатель"), name_text),
            Column(tr("по e-qaimə"), lambda r: r.by_invoice, money=True, group=received),
            Column(tr("без номера"), lambda r: r.no_number, money=True, group=received),
            Column(tr("на депозит ƏDV"), lambda r: r.deposit, money=True, group=received),
            Column(tr("Стоимость"), lambda r: r.amount, money=True, group=issued),
            Column(tr("ƏDV"), lambda r: r.vat, money=True, group=issued),
            Column(tr("Начислено ƏDV"), lambda r: r.owed, money=True, warn=check_text),
            Column(tr("Аванс"), balance("advance"), money=True, group=end),
            Column(tr("Не оплачено"), balance("unpaid"), money=True, group=end),
        ]
        rows: list[ReceiptLine] = []
        for buyer in data.buyers:
            rows += [buyer, *buyer.lines]
        if rows:
            data.total.name = tr("Итого")
            rows.append(data.total)
        total = data.total
        self.model.set(
            columns,
            rows,
            emphasis=lambda r: isinstance(r, BuyerRow),
            muted=lambda r: not isinstance(r, BuyerRow),
            total=lambda r: r is total,
        )
        text = tr(
            "Начислено ƏDV за период: {owed}   ·   аванс: {advance}   ·   не оплачено: {unpaid}",
            owed=money(total.owed, blank_zero=False),
            advance=money(total.advance, blank_zero=False),
            unpaid=money(total.unpaid, blank_zero=False),
        )
        if data.warnings:
            text += "   ·   " + tr("Предупреждений: {n}", n=data.warnings)
        self.footer.setText(html.escape(text).replace("  ", "&nbsp; ") + warnings_text(data))
        self._buyers = {id(ln): b for b in data.buyers for ln in b.lines}

    def drill(self, row) -> None:
        if row is None or row is self.model.rows[-1]:
            return
        if not isinstance(row, BuyerRow) and row.document_id:
            self.open_document.emit(row.document_id)
            return
        buyer = row if isinstance(row, BuyerRow) else self._buyers.get(id(row))
        if buyer is not None and buyer.counterparty_id is not None:
            params = replace(self.params, subconto=(buyer.counterparty_id,))
            self.open_report.emit("subconto_card", 0, params)
