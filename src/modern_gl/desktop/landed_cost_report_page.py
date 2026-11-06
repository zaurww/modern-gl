"""«Əlavə xərclər» report: the receipts of the period on a customs declaration or with
landed costs. Under each declaration its goods: the price by the invoice, what each kind
of expense added, the cost with them and by how many percent it grew; a unit's price
before and after. Enter opens the receipt; the menu, the expense documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QLineEdit

from modern_gl.application.inventory import format_quantity, unit_price
from modern_gl.desktop.reports_page import Column, MenuAction, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, button, money
from modern_gl.domain.currency import format_unit_rate, unit_rate
from modern_gl.domain.dates import ru_date
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.inventory import (
    Declaration,
    LandedLine,
    landed_cost_report,
    percent_added,
)


def percent_text(hundredths: int | None) -> str:
    return "" if not hundredths else f"+{format_minor(hundredths)} %"


@dataclass
class _Row:
    """A declaration (its totals), one of its goods, or the total of the period."""

    label: str
    quantity: str | None = None  # None: a declaration's or the total's (no dash)
    in_currency: str | None = None
    cost: int = 0
    expenses: dict[str, int] = field(default_factory=dict)
    added: int = 0
    total: int = 0
    percent: int | None = None
    price: int | None = None
    price_after: int | None = None
    declaration: Declaration | None = None
    is_header: bool = False
    is_total: bool = False


def declaration_title(d: Declaration) -> str:
    """«AZ2603101234 · 10.03.2026 · Supplier» (an e-qaimə says so, a receipt without
    a number shows its own)."""
    if d.invoice:
        parts = [d.invoice if d.invoice_kind == CUSTOMS else f"E-qaimə {d.invoice}"]
    else:
        parts = [tr("Поступление №{n}", n=d.number)]
    parts.append(ru_date(d.doc_date))
    if d.supplier:
        parts.append(d.supplier)
    return "  ·  ".join(parts)


def _line_row(line: LandedLine, currency: str | None, declaration: Declaration) -> _Row:
    def per_unit(amount: int) -> int | None:
        return unit_price(amount, line.quantity)

    in_currency = ""
    if currency and line.currency_amount is not None:
        in_currency = f"{money(line.currency_amount, False)} {currency}"
    return _Row(
        line.item_name,
        f"{format_quantity(line.quantity, line.precision)} {line.unit}",
        in_currency,
        line.cost,
        line.expenses,
        line.added,
        line.total,
        line.percent,
        per_unit(line.cost),
        per_unit(line.total),
        declaration,
    )


def report_rows(declarations: list[Declaration]) -> list[_Row]:
    rows: list[_Row] = []
    for d in declarations:
        in_currency = None
        if d.currency and d.currency_amount is not None:
            in_currency = f"{money(d.currency_amount, False)} {d.currency}"
            if d.rate:
                in_currency += f"  ×  {format_unit_rate(unit_rate(d.rate))}"
        rows.append(
            _Row(
                declaration_title(d),
                None,
                in_currency,
                d.cost,
                d.expenses,
                d.added,
                d.total,
                d.percent,
                declaration=d,
                is_header=True,
            )
        )
        rows += [_line_row(line, d.currency, d) for line in d.lines]
    if len(declarations) > 1:
        expenses: dict[str, int] = {}
        for d in declarations:
            for kind, amount in d.expenses.items():
                expenses[kind] = expenses.get(kind, 0) + amount
        cost, added = sum(d.cost for d in declarations), sum(d.added for d in declarations)
        rows.append(
            _Row(
                tr("Итого"),
                cost=cost,
                expenses=expenses,
                added=added,
                total=cost + added,
                percent=percent_added(added, cost),
                is_total=True,
            )
        )
    return rows


class LandedCostReportPage(ReportPage):
    key = ("landed_report",)
    has_book = False  # the warehouse keeps one book
    own_period = True  # a list to work in: the year, whatever a report was asked for
    open_inventory_document = Signal(int)

    def __init__(self, session: Session) -> None:
        year = session.working_date.year
        super().__init__(
            session, tr("Əlavə xərclər"), ReportParams(date(year, 1, 1), date(year, 12, 31))
        )
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Номер, поставщик или товар"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        self.header.add_action(self.search)
        copy = button(tr("Копировать для Excel"), "flat")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text()))
        self.header.add_action(copy)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Нет деклараций"),
            tr(
                "Здесь видны поступления по таможенной декларации и с дополнительными "
                "расходами: сколько стоил товар, что добавили расходы и на сколько процентов."
            ),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Əlavə xərclər")

    def build(self) -> None:
        kinds, declarations = landed_cost_report(
            self.s.conn,
            self.s.company_id,
            self.params.date_from.isoformat(),
            self.params.date_to.isoformat(),
        )
        needle = fold(self.search.text().strip())
        if needle:
            declarations = [d for d in declarations if needle in fold(_searched(d))]
        group = tr("Дополнительные расходы")
        columns = [
            Column(tr("Декларация / товар"), lambda r: r.label, width=1),  # never cut
            Column(tr("Количество"), lambda r: r.quantity, right=True),
            *(
                [Column(tr("В валюте"), lambda r: r.in_currency, right=True)]
                if any(d.currency for d in declarations)
                else []
            ),
            # first what matters: the price, what the expenses added, by how much, the cost
            Column(tr("Стоимость"), lambda r: r.cost, money=True),
            Column(tr("Расходы"), lambda r: r.added, money=True),
            Column("%", lambda r: percent_text(r.percent), right=True),
            Column(tr("С расходами"), lambda r: r.total, money=True),
            Column(tr("Цена"), lambda r: r.price, money=True),
            Column(tr("Цена с расходами"), lambda r: r.price_after, money=True),
            *[  # then each kind of expense
                Column(kind, lambda r, k=kind: r.expenses.get(k, 0), money=True, group=group)
                for kind in kinds
            ],
        ]
        rows = report_rows(declarations)
        self.model.set(
            columns,
            rows,
            emphasis=lambda r: r.is_header or r.is_total,
            section=lambda r: r.is_header,
            total=lambda r: r.is_total,
        )
        cost = sum(d.cost for d in declarations)
        added = sum(d.added for d in declarations)
        self.footer.setText(
            tr(
                "{n} поступлений · стоимость {cost} · расходы {added} ({percent})",
                n=len(declarations),
                cost=money(cost, False),
                added=money(added, False),
                percent=percent_text(percent_added(added, cost)) or "0 %",
            )
            if declarations
            else ""
        )

    def text(self) -> str:
        """The table as tab-separated lines with a header, for Excel."""
        model, columns = self.model, self.model.columns
        lines = ["\t".join(c.title for c in columns)]
        for row in range(model.rowCount()):
            cells = []
            for n, column in enumerate(columns):
                text = str(model.index(row, n).data() or "")
                if column.money:
                    text = text.replace(" ", "").replace(" ", "").replace("—", "")
                cells.append(text)
            lines.append("\t".join(cells))
        return "\n".join(lines) + "\n"

    # ---- drill -----------------------------------------------------------------------

    def drill(self, row: _Row | None) -> None:
        if row is not None and row.declaration is not None:
            self.open_inventory_document.emit(row.declaration.receipt_id)

    def menu_actions(self, row: _Row | None) -> list[MenuAction | None]:
        d = row.declaration if row is not None else None
        if d is None:
            return []
        actions: list[MenuAction | None] = [
            (
                tr("Открыть поступление №{n}", n=d.number),
                lambda: self.open_inventory_document.emit(d.receipt_id),
            )
        ]
        if d.expense_documents:
            actions.append(None)
        actions += [
            (
                tr("Открыть доп. расходы №{n} от {date}", n=number, date=ru_date(day)),
                lambda doc_id=doc_id: self.open_inventory_document.emit(doc_id),
            )
            for doc_id, number, day in d.expense_documents
        ]
        return actions


def _searched(d: Declaration) -> str:
    return " ".join([d.invoice, d.supplier, str(d.number), *(x.item_name for x in d.lines)])
