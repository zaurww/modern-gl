"""«Поступления и e-qaimə» and «Оплаты поставщикам и e-qaimə»: each counterparty's money
against their e-qaimə, the ƏDV owed or credited, what is open at the period's end and what
wants a look (`reporting/vat_receipts`, `reporting/vat_payments`). Under a counterparty —
their e-qaimə and the money without a number. A double click on an e-qaimə opens its
document, on a counterparty or their advance — the card of the counterparty (D126), with
the statements; a number in a payment is set in the bank (D67)."""

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
from modern_gl.reporting.vat_payments import vat_payments
from modern_gl.reporting.vat_receipts import (
    PartyRow,
    ReceiptLine,
    VatReceipts,
    vat_receipts,
    warning,
)

SHOWN_WARNINGS = 3  # in the footer; the rest are counted, each is on its row's cell


def name_text(row: ReceiptLine) -> str:
    if isinstance(row, PartyRow):
        return row.name or tr("Без контрагента")
    if row.invoice is None:
        return INDENT + tr("аванс")
    return INDENT + row.invoice


def check_text(row: ReceiptLine) -> str | None:
    return warning(row) if isinstance(row, PartyRow) else None


def warnings_text(data: VatReceipts) -> str:
    """«Бета — ƏDV e-qaimə пришёл…» in red, a line each, the first few."""
    found = [(b.name, text) for b in data.parties if (text := warning(b))]
    lines = [f"{name or tr('Без контрагента')} — {text}" for name, text in found]
    if len(lines) > SHOWN_WARNINGS:
        rest = len(lines) - SHOWN_WARNINGS
        lines = [*lines[:SHOWN_WARNINGS], tr("и ещё {n}", n=rest)]
    return "".join(f'<br><span style="color: {P.red}">{html.escape(t)}</span>' for t in lines)


class VatReceiptsPage(ReportPage):
    """The buyers; `VatPaymentsPage` — the suppliers."""

    key = ("vat_receipts",)
    has_book = False  # the facts are the common book's

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, self.title(), params)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState("○", *self.empty_texts())
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Поступления и e-qaimə")

    def empty_texts(self) -> tuple[str, str]:
        return (
            tr("Поступлений и e-qaimə покупателям за период нет"),
            tr(
                "По каждому покупателю: деньги с номером e-qaimə и без, выписанные e-qaimə, "
                "начисленный ƏDV, аванс и неоплаченное на конец периода."
            ),
        )

    def fetch(self, conn: Connection) -> VatReceipts:
        return vat_receipts(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def captions(self) -> tuple[str, str, str, str]:
        """The counterparty, the money, the deposit, the ƏDV of the rule."""
        return tr("Покупатель"), tr("Поступило"), tr("на депозит ƏDV"), tr("Начислено ƏDV")

    def totals_text(self, total: PartyRow) -> str:
        return tr(
            "Начислено ƏDV за период: {owed}   ·   аванс: {advance}   ·   не оплачено: {unpaid}",
            owed=money(total.tax, blank_zero=False),
            advance=money(total.advance, blank_zero=False),
            unpaid=money(total.unpaid, blank_zero=False),
        )

    def present(self, data: VatReceipts) -> None:
        who, moved, deposit, tax = self.captions()
        issued, end = tr("E-qaimə"), tr("На конец периода")

        def balance(name: str):
            return lambda r: getattr(r, name) if isinstance(r, PartyRow) else None

        columns = [
            Column(who, name_text),
            Column(tr("по e-qaimə"), lambda r: r.by_invoice, money=True, group=moved),
            Column(tr("без номера"), lambda r: r.no_number, money=True, group=moved),
            Column(deposit, lambda r: r.deposit, money=True, group=moved),
            Column(tr("Стоимость"), lambda r: r.amount, money=True, group=issued),
            Column(tr("ƏDV"), lambda r: r.vat, money=True, group=issued),
            Column(tax, lambda r: r.tax, money=True, warn=check_text),
            Column(tr("Аванс"), balance("advance"), money=True, group=end),
            Column(tr("Не оплачено"), balance("unpaid"), money=True, group=end),
        ]
        rows: list[ReceiptLine] = []
        for party in data.parties:
            rows += [party, *party.lines]
        if rows:
            data.total.name = tr("Итого")
            rows.append(data.total)
        total = data.total
        self.model.set(
            columns,
            rows,
            emphasis=lambda r: isinstance(r, PartyRow),
            muted=lambda r: not isinstance(r, PartyRow),
            total=lambda r: r is total,
        )
        text = self.totals_text(total)
        if data.warnings:
            text += "   ·   " + tr("Предупреждений: {n}", n=data.warnings)
        self.footer.setText(html.escape(text).replace("  ", "&nbsp; ") + warnings_text(data))
        self._parties = {id(ln): b for b in data.parties for ln in b.lines}

    def drill(self, row) -> None:
        if row is None or row is self.model.rows[-1]:
            return
        if not isinstance(row, PartyRow) and row.document_id:
            self.open_document.emit(row.document_id)
            return
        party = row if isinstance(row, PartyRow) else self._parties.get(id(row))
        if party is not None and party.counterparty_id is not None:
            params = replace(self.params, subconto=(party.counterparty_id,))
            self.open_report.emit("subconto_card", 0, params)


class VatPaymentsPage(VatReceiptsPage):
    key = ("vat_payments",)

    def title(self) -> str:
        return tr("Оплаты поставщикам и e-qaimə")

    def empty_texts(self) -> tuple[str, str]:
        return (
            tr("Оплат и e-qaimə поставщиков за период нет"),
            tr(
                "По каждому поставщику: деньги с номером e-qaimə и без, полученные e-qaimə, "
                "зачтённый ƏDV, аванс и неоплаченное на конец периода."
            ),
        )

    def fetch(self, conn: Connection) -> VatReceipts:
        return vat_payments(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def captions(self) -> tuple[str, str, str, str]:
        return tr("Поставщик"), tr("Оплачено"), tr("с депозита ƏDV"), tr("Зачтено ƏDV")

    def totals_text(self, total: PartyRow) -> str:
        return tr(
            "Зачтено ƏDV за период: {credited}   ·   аванс: {advance}   ·   не оплачено: {unpaid}",
            credited=money(total.tax, blank_zero=False),
            advance=money(total.advance, blank_zero=False),
            unpaid=money(total.unpaid, blank_zero=False),
        )
