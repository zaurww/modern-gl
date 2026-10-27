"""Финансовая отчётность (D99, D100): the balance sheet on the period's last day, the
profit and loss or the cash flow of the period — one place, a switch between them; lines
by account type. A line opens into its accounts, in the profit and loss also into the
cost items (D102); a double click on an account or an item opens its card, and the card
the documents — every figure leads to where it came from."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal

from modern_gl.desktop.preferences import STATEMENTS_DETAIL, STATEMENTS_VIEW, prefs
from modern_gl.desktop.reports_page.statement_columns import (
    ColumnsChoice,
    amount_columns,
    column_period,
    periods_of,
)
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import segments
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.cash_flow import cash_flow
from modern_gl.reporting.profit_loss import profit_and_loss
from modern_gl.reporting.statements import (
    ACCOUNTS,
    ITEMS,
    TYPES,
    Line,
    Statement,
    balance_sheet,
)

BALANCE, PROFIT, CASH = "balance", "profit", "cash"
# the parts of the balance sheet: their subtotal reads «Итого: …»
SECTIONS = (
    "Оборотные активы",
    "Долгосрочные активы",
    "Краткосрочные обязательства",
    "Долгосрочные обязательства",
    "Капитал",
)
INDENT = "      "


class StatementsPage(ReportPage):
    key = ("statements",)
    choosable_columns = False  # periods: «Колонки ▾» by the period chooses them
    view_changed = Signal()  # the sidebar chooses the pinned view shown (D114)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Финансовая отчётность"), params)
        views, self.view_buttons = segments(
            [(BALANCE, "Баланс"), (PROFIT, "Прибыли и убытки"), (CASH, "Движение денег")],
            self.refresh,
        )
        self.balance_button = self.view_buttons[BALANCE]
        self.profit_button = self.view_buttons[PROFIT]
        self.cash_button = self.view_buttons[CASH]
        details, self.detail_buttons = segments(
            [(TYPES, "Кратко"), (ACCOUNTS, "По счетам"), (ITEMS, "По статьям")], self.refresh
        )
        remembered = prefs()
        view = remembered.view(STATEMENTS_VIEW, BALANCE)
        detail = remembered.view(STATEMENTS_DETAIL, ACCOUNTS)
        self.view_buttons.get(view, self.balance_button).setChecked(True)
        self.detail_buttons.get(detail, self.detail_buttons[ACCOUNTS]).setChecked(True)
        self.columns = ColumnsChoice(self.refresh)  # months side by side, a comparison (D107)
        self.header.add_action(views)
        self.add_to_bar(details, self.columns.button)  # by the period: how much of it
        self.refresh()

    def title(self) -> str:
        return tr("Финансовая отчётность")

    def export_title(self) -> str:
        names = {BALANCE: "Баланс", PROFIT: "Прибыли и убытки", CASH: "Движение денег"}
        return tr(names[self.view])

    def show_view(self, view: str) -> None:
        """«Баланс», «Прибыли и убытки» or «Движение денег» chosen from «Отчёты» (D114)."""
        if view in self.view_buttons and view != self.view:
            self.view_buttons[view].setChecked(True)
            self.refresh()

    def nav_key(self) -> tuple:
        return (*self.key, self.view)

    @property
    def view(self) -> str:
        return next((k for k, b in self.view_buttons.items() if b.isChecked()), BALANCE)

    @property
    def detail(self) -> str:
        """Cost items are a part of the profit and loss only; elsewhere — the accounts."""
        chosen = next((k for k, b in self.detail_buttons.items() if b.isChecked()), ACCOUNTS)
        return ACCOUNTS if chosen == ITEMS and self.view != PROFIT else chosen

    def refresh(self) -> None:
        if hasattr(self, "detail_buttons"):  # the first refresh comes from ReportPage
            self.detail_buttons[ITEMS].setVisible(self.view == PROFIT)
            remembered = prefs()
            if remembered.view(STATEMENTS_VIEW, "") != self.view:
                self.view_changed.emit()
            remembered.set_view(STATEMENTS_VIEW, self.view)
            chosen = next(k for k, b in self.detail_buttons.items() if b.isChecked())
            remembered.set_view(STATEMENTS_DETAIL, chosen)
        super().refresh()

    @property
    def periods(self):
        """The periods of the columns (a balance: the days are their ends)."""
        mode = self.columns.mode if hasattr(self, "columns") else "one"
        period = (self.params.date_from, self.params.date_to)
        return periods_of(mode, period, self.view == BALANCE)

    def job(self):
        cid, p, view, detail = self.s.company_id, self.params, self.view, self.detail
        periods = self.periods
        if view == BALANCE:
            days = [last for _, last in periods]
            return lambda conn: balance_sheet(conn, cid, p.date_to, p.layers, detail, days)
        statement = cash_flow if view == CASH else profit_and_loss
        return lambda conn: statement(conn, cid, p.date_from, p.date_to, p.layers, detail, periods)

    def fetch(self, conn: Connection) -> Statement:
        return self.job()(conn)

    def present(self, data: Statement) -> None:
        mode = self.columns.mode if hasattr(self, "columns") else "one"
        columns = [
            Column(tr("Статья"), self._title),
            *amount_columns(mode, self.periods, self.view == BALANCE),
        ]
        self.model.set(
            columns,
            data.lines,
            emphasis=lambda r: r.kind in ("subtotal", "total"),
            muted=lambda r: r.kind == "item",
            total=lambda r: r.kind == "total",
            section=lambda r: r.kind == "heading",
        )
        self._footer(data)

    @staticmethod
    def _title(r: Line) -> str:
        if r.kind == "account":
            return INDENT * 2 + r.title
        if r.kind == "item":
            return INDENT * (2 if r.under_line else 3) + (r.title or tr("Без статьи"))
        if r.kind == "line":
            return INDENT + tr(r.title)
        if r.kind == "subtotal" and r.title in SECTIONS:
            return tr("Итого: {what}", what=tr(r.title))
        return tr(r.title)

    def _footer(self, data: Statement) -> None:
        untyped = any(ln.account_type == "" for ln in data.lines)
        notes = []
        if self.view == BALANCE:
            notes.append(
                tr("Актив и пассив сходятся  ✓")
                if not data.unbalanced
                else tr("Внимание: актив и пассив не сходятся")
            )
        elif self.view == CASH:
            notes.append(tr("Остаток денег сходится с потоками  ✓"))
        if untyped:
            notes.append(tr("Есть счета без типа — укажите тип в плане счетов"))
        notes.append(tr("Двойной щелчок по счёту — его карточка"))
        self.footer.setText("      ".join(notes))
        self.footer.setStyleSheet(f"color: {P.red};" if data.unbalanced else "")

    def drill(self, row: Line | None) -> None:
        """An account, an item or a line of one account: its card for the period (the
        balance sheet: the year up to the day). A line in «Кратко»: open the accounts. The
        profit of the period in the balance sheet: the profit and loss."""
        if row is None:
            return
        params = self.params
        cell = column_period(self.columns.mode, self.periods, self.table.currentIndex().column())
        if cell is not None:  # a figure of a month: the card of that month
            params = replace(params, date_from=cell[0], date_to=cell[1])
        if self.view == BALANCE:  # a balance is read from the start of its year
            params = replace(params, date_from=params.date_to.replace(month=1, day=1))
        if row.kind in ("account", "line") and row.account_id is not None:
            self.open_report.emit("card", row.account_id, params)
        elif row.kind == "item" and row.account_id is not None:
            self.open_report.emit("card", row.account_id, replace(params, subconto=(row.value_id,)))
        elif row.kind == "line" and row.account_type is not None and self.detail == TYPES:
            self.detail_buttons[ACCOUNTS].setChecked(True)
            self.refresh()
        elif row.kind == "line" and row.title == "Прибыль (убыток) текущего периода":
            self.profit_button.setChecked(True)
            self.refresh()
