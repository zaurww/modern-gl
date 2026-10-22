"""Финансовая отчётность (D99): the balance sheet on the period's last day, or the profit
and loss of the period — one place, a switch between the two; lines by account type."""

from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QWidget

from modern_gl.desktop.reports_page.table import figure
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import button, ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.statements import Line, Statement, balance_sheet, profit_and_loss

BALANCE, PROFIT = "balance", "profit"
# the parts of the balance sheet: their subtotal reads «Итого: …»
SECTIONS = (
    "Оборотные активы",
    "Долгосрочные активы",
    "Краткосрочные обязательства",
    "Долгосрочные обязательства",
    "Капитал",
)


class StatementsPage(ReportPage):
    key = ("statements",)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Финансовая отчётность"), params)
        self.views = QButtonGroup(self)
        switch = QWidget()
        row = QHBoxLayout(switch)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.balance_button = button(tr("Баланс"), "segment")
        self.profit_button = button(tr("Прибыли и убытки"), "segment")
        for b in (self.balance_button, self.profit_button):
            b.setCheckable(True)
            b.clicked.connect(lambda _=False: self.refresh())
            self.views.addButton(b)
            row.addWidget(b)
        self.balance_button.setChecked(True)
        self.header.add_action(switch)
        self.refresh()

    def title(self) -> str:
        return tr("Финансовая отчётность")

    @property
    def view(self) -> str:
        return PROFIT if self.profit_button.isChecked() else BALANCE

    def job(self):
        cid, p, view = self.s.company_id, self.params, self.view
        if view == BALANCE:
            return lambda conn: balance_sheet(conn, cid, p.date_to, p.layers)
        return lambda conn: profit_and_loss(conn, cid, p.date_from, p.date_to, p.layers)

    def fetch(self, conn: Connection) -> Statement:
        return self.job()(conn)

    def present(self, data: Statement) -> None:
        indent = "      "
        columns = [
            Column(tr("Статья"), lambda r: self._title(r, indent)),
            Column(
                self._amount_title(),
                lambda r: None if r.kind == "heading" else figure(r.amount),
                right=True,
            ),
        ]
        self.model.set(
            columns,
            data.lines,
            emphasis=lambda r: r.kind in ("subtotal", "total"),
            total=lambda r: r.kind == "total",
            section=lambda r: r.kind == "heading",
        )
        self._footer(data)

    @staticmethod
    def _title(r: Line, indent: str) -> str:
        if r.kind == "line":
            return indent + tr(r.title)
        if r.kind == "subtotal" and r.title in SECTIONS:
            return tr("Итого: {what}", what=tr(r.title))
        return tr(r.title)

    def _amount_title(self) -> str:
        if self.view == BALANCE:
            return tr("На {day}", day=ru_date(self.params.date_to.isoformat()))
        return tr("За период")

    def _footer(self, data: Statement) -> None:
        untyped = any(ln.account_type == "" for ln in data.lines)
        notes = []
        if self.view == BALANCE:
            notes.append(
                tr("Актив и пассив сходятся  ✓")
                if not data.unbalanced
                else tr("Внимание: актив и пассив не сходятся")
            )
        if untyped:
            notes.append(tr("Есть счета без типа — укажите тип в плане счетов"))
        self.footer.setText("      ".join(notes))
        self.footer.setStyleSheet(f"color: {P.red};" if data.unbalanced else "")

    def drill(self, row: Line) -> None:
        pass  # a line is several accounts: the ОСВ shows them
