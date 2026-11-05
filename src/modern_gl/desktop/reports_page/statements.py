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
    column_element,
    column_period,
    periods_of,
)
from modern_gl.desktop.reports_page.table import INDENT
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import segments
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.cash_flow import cash_flow
from modern_gl.reporting.columns import SUBCONTO, Amounts
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
    N_("Оборотные активы"),
    N_("Долгосрочные активы"),
    N_("Краткосрочные обязательства"),
    N_("Долгосрочные обязательства"),
    N_("Капитал"),
)


class StatementsPage(ReportPage):
    key = ("statements",)
    choosable_columns = False  # periods: «Колонки ▾» by the period chooses them
    view_changed = Signal()  # the sidebar chooses the pinned view shown (D114)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Финансовая отчётность"), params)
        views, self.view_buttons = segments(
            [
                (BALANCE, N_("Баланс")),
                (PROFIT, N_("Прибыли и убытки")),
                (CASH, N_("Движение денег")),
            ],
            self.refresh,
        )
        self.balance_button = self.view_buttons[BALANCE]
        self.profit_button = self.view_buttons[PROFIT]
        self.cash_button = self.view_buttons[CASH]
        details, self.detail_buttons = segments(
            [(TYPES, N_("Кратко")), (ACCOUNTS, N_("По счетам")), (ITEMS, N_("По статьям"))],
            self.refresh,
        )
        remembered = prefs()
        view = remembered.view(STATEMENTS_VIEW, BALANCE)
        detail = remembered.view(STATEMENTS_DETAIL, ACCOUNTS)
        self.view_buttons.get(view, self.balance_button).setChecked(True)
        self.detail_buttons.get(detail, self.detail_buttons[ACCOUNTS]).setChecked(True)
        # months side by side, a comparison (D107); the profit and loss by the elements of
        # a directory and with a share of the revenue (D188)
        self.columns = ColumnsChoice(self.refresh, self._directories, lambda: self.view == PROFIT)
        self.split: list[tuple[int | None, str]] = []
        self.header.add_action(views)
        self.add_to_bar(details, self.columns.button)  # by the period: how much of it
        self.refresh()

    def title(self) -> str:
        return tr("Финансовая отчётность")

    def export_title(self) -> str:
        names = {BALANCE: N_("Баланс"), PROFIT: N_("Прибыли и убытки"), CASH: N_("Движение денег")}
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
    def mode(self) -> str:
        return self.columns.effective() if hasattr(self, "columns") else "one"

    @property
    def periods(self):
        """The periods of the columns (a balance: the days are their ends)."""
        period = (self.params.date_from, self.params.date_to)
        return periods_of(self.mode, period, self.view == BALANCE)

    def _directories(self) -> list[tuple[int, str]]:
        """The directories on the income and expense accounts, by name."""
        catalog = self.s.catalog
        kinds = {
            k
            for a in catalog.accounts.values()
            if a.account_class in ("revenue", "expense")
            for k in a.sc_kinds
            if k is not None
        }
        return sorted(((k, catalog.kinds[k]) for k in kinds), key=lambda x: x[1].casefold())

    def job(self):
        cid, p, view, detail = self.s.company_id, self.params, self.view, self.detail
        periods = self.periods
        if view == BALANCE:
            days = [last for _, last in periods]
            return lambda conn: balance_sheet(conn, cid, p.date_to, p.layers, detail, days)
        if view == CASH:
            return lambda conn: cash_flow(
                conn, cid, p.date_from, p.date_to, p.layers, detail, periods
            )
        split = self.columns.kind_id() if self.mode == SUBCONTO else None
        return lambda conn: profit_and_loss(
            conn, cid, p.date_from, p.date_to, p.layers, detail, periods, split
        )

    def fetch(self, conn: Connection) -> Statement:
        return self.job()(conn)

    def present(self, data: Statement) -> None:
        self.split = data.split
        revenue = None
        if self.view == PROFIT and getattr(self.columns, "percent", False):
            sales = next(
                (ln for ln in data.lines if ln.kind == "line" and ln.account_type == "sales"), None
            )
            revenue = sales.amount if sales is not None else Amounts()
        columns = [
            Column(tr("Статья"), self._title),
            *amount_columns(self.mode, self.periods, self.view == BALANCE, data.split, revenue),
        ]
        self.model.set(
            columns,
            data.lines,
            emphasis=lambda r: r.kind in ("group", "subtotal", "total"),
            muted=lambda r: r.kind == "item",
            total=lambda r: r.kind == "total",
            section=lambda r: r.kind == "heading",
        )
        self._footer(data)

    @staticmethod
    def _title(r: Line) -> str:
        if r.kind in ("account", "group"):
            return INDENT * (2 + r.depth) + r.title
        if r.kind == "item":
            return INDENT * ((2 if r.under_line else 3) + r.depth) + (r.title or tr("Без статьи"))
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
        at = self.table.currentIndex().column()
        column = self.model.columns[at] if 0 <= at < len(self.model.columns) else None
        cell = column_period(self.mode, self.periods, column)
        if cell is not None:  # a figure of a month: the card of that month
            params = replace(params, date_from=cell[0], date_to=cell[1])
        if self.view == BALANCE:  # a balance is read from the start of its year
            params = replace(params, date_from=params.date_to.replace(month=1, day=1))
        if row.kind in ("account", "line") and row.account_id is not None:
            # a figure of an element: the card of it, when the directory is the first
            # subconto of the account (the card filters by it)
            element = column_element(column, self.split) if self.mode == SUBCONTO else None
            first = self.s.catalog.accounts[row.account_id].sc_kinds[0]
            if element is not None and first == self.columns.kind_id():
                params = replace(params, subconto=(element,))
            self.open_report.emit("card", row.account_id, params)
        elif row.kind == "item" and row.account_id is not None:
            self.open_report.emit("card", row.account_id, replace(params, subconto=(row.value_id,)))
        elif row.kind == "line" and row.account_type is not None and self.detail == TYPES:
            self.detail_buttons[ACCOUNTS].setChecked(True)
            self.refresh()
        elif row.kind == "line" and row.title == "Прибыль (убыток) текущего периода":
            self.profit_button.setChecked(True)
            self.refresh()
