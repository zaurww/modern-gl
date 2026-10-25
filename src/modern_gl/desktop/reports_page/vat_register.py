"""«Реестр e-qaimə» for the ƏDV declaration: the purchases, then the sales of the period,
each with its totals by rate (`reporting/vat_register`). A double click opens the
document of the e-qaimə."""

from __future__ import annotations

import html
from dataclasses import dataclass

from modern_gl.desktop.reports_page.vat_credit import document_text
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import EmptyState, MenuItem, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat_register import (
    BOOKS_CHANGED,
    NOT_RECONCILED,
    RECONCILED,
    PortalCheck,
    RateTotal,
    RegisterRow,
    VatRegister,
    vat_register,
)

HEADING, ROW, TOTAL = "heading", "row", "total"


@dataclass(frozen=True)
class Line:
    kind: str
    row: RegisterRow | None = None
    rate: RateTotal | None = None
    text: str = ""

    def figure(self, name: str) -> int | None:
        source = self.row or self.rate
        return getattr(source, name) if source is not None else None


def rate_text(rate: int | None) -> str:
    return tr("без ƏDV") if rate is None else f"{rate}%"


def portal_text(checks: list[PortalCheck]) -> str:
    """«Покупки — сверены с порталом · продажи — …»: what agrees quieter, a change red."""
    parts = []
    for check in checks:
        side = tr("продажи") if check.outgoing else tr("покупки")
        if not parts:  # the line starts with it
            side = side[:1].upper() + side[1:]
        if check.state == RECONCILED:
            text, color = tr("{side} — сверены с порталом", side=side), P.muted
        elif check.state == NOT_RECONCILED:
            text, color = tr("{side} — не сверены с порталом", side=side), P.text
        elif check.state == BOOKS_CHANGED:
            text = tr("{side} — после сверки изменились в книге, сверьте снова", side=side)
            color = P.red
        else:
            text = tr(
                "{side} — после сверки изменились на портале: {numbers}",
                side=side,
                numbers=", ".join(check.numbers),
            )
            color = P.red
        parts.append(f'<span style="color: {color}">{_rich(text)}</span>')
    return _rich("   ·   ").join(parts)


def _rich(text: str) -> str:
    """Plain text in the footer's rich text: its runs of spaces kept."""
    return html.escape(text).replace("  ", "&nbsp; ")


def lines(data: VatRegister) -> list[Line]:
    """A heading, the rows, a total for each rate — purchases, then sales."""
    found: list[Line] = []
    for title, rows, totals in (
        (tr("Покупки"), data.purchases, data.purchase_rates),
        (tr("Продажи"), data.sales, data.sale_rates),
    ):
        if not rows:
            continue
        found.append(Line(HEADING, text=title))
        found += [Line(ROW, row=r) for r in rows]
        found += [
            Line(TOTAL, rate=t, text=tr("Итого {rate}: {n}", rate=rate_text(t.rate), n=t.count))
            for t in totals
        ]
    return found


class VatRegisterPage(ReportPage):
    key = ("vat_register",)
    has_book = False  # the facts are the common book's

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Реестр e-qaimə"), params)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("E-qaimə за период нет"),
            tr(
                "В реестр попадают проведённые покупки и продажи с номером e-qaimə и "
                "таможенные декларации — по дню первой проводки."
            ),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Реестр e-qaimə")

    def fetch(self, conn: Connection) -> VatRegister:
        return vat_register(conn, self.s.company_id, self.params.date_from, self.params.date_to)

    def present(self, data: VatRegister) -> None:
        def row(get):
            return lambda ln: get(ln.row) if ln.row is not None else ""

        columns = [
            Column(
                tr("Дата"),
                lambda ln: (
                    ln.text if ln.kind == HEADING else row(lambda r: ru_date(r.doc_date))(ln)
                ),
                width=100,
            ),
            Column(tr("E-qaimə / ГТД"), row(document_text), width=140),
            Column(
                tr("Контрагент"),
                lambda ln: ln.text if ln.kind == TOTAL else row(lambda r: r.counterparty)(ln),
            ),
            Column(tr("VÖEN"), row(lambda r: r.tax_id), width=100, optional=True),
            Column(tr("Сумма без ƏDV"), lambda ln: ln.figure("amount"), money=True),
            Column(tr("ƏDV"), lambda ln: ln.figure("vat"), money=True),
            Column(tr("Всего"), lambda ln: ln.figure("total"), money=True),
            Column(tr("Не оплачено"), lambda ln: ln.row.unpaid if ln.row else None, money=True),
        ]
        self.model.set(
            columns,
            lines(data),
            total=lambda ln: ln.kind == TOTAL,
            section=lambda ln: ln.kind == HEADING,
        )
        totals = tr(
            "Покупки: ƏDV {bought}   ·   продажи: ƏDV {sold}",
            bought=money(sum(r.vat for r in data.purchases), blank_zero=False),
            sold=money(sum(r.vat for r in data.sales), blank_zero=False),
        )
        self.footer.setText(f"{_rich(totals)}<br>{portal_text(data.checks)}")

    def more_items(self) -> list[MenuItem]:
        """The reconciliation with the portal of the same period (D53), unless viewing."""
        if self.s.read_only:
            return super().more_items()
        return [
            (tr("Сверить покупки с порталом…"), lambda: self.reconcile("receipt")),
            (tr("Сверить продажи с порталом…"), lambda: self.reconcile("sale")),
            None,
            *super().more_items(),
        ]

    def reconcile(self, direction: str) -> None:
        from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog

        dialog = EqaimeReconciliationDialog(self.s, self, direction=direction)
        dialog.period_field.set_period(self.params.date_from, self.params.date_to)
        dialog.exec()
        self.refresh()
        if dialog.chosen_document is not None:
            self.open_document.emit(dialog.chosen_document)

    def drill(self, row) -> None:
        if row is not None and row.row is not None and row.row.document_id:
            self.open_document.emit(row.row.document_id)
