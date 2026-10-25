"""«Реестр e-qaimə» for the ƏDV declaration: the purchases, then the sales of the period,
each with its totals by rate (`reporting/vat_register`). A double click opens the
document of the e-qaimə."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.desktop.reports_page.vat_credit import document_text
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat_register import RateTotal, RegisterRow, VatRegister, vat_register

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
        self.footer.setText(
            tr(
                "Покупки: ƏDV {bought}   ·   продажи: ƏDV {sold}",
                bought=money(sum(r.vat for r in data.purchases), blank_zero=False),
                sold=money(sum(r.vat for r in data.sales), blank_zero=False),
            )
        )

    def drill(self, row) -> None:
        if row is not None and row.row is not None and row.row.document_id:
            self.open_document.emit(row.row.document_id)
