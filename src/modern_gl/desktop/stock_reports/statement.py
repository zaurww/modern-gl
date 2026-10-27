"""«Ведомость по складу»: at the start, in, out and at the end of a period, in quantity
and value (ERPNext Stock Balance, inFlow Movement Summary); the end of the period is the
stock at a date. The check line compares the warehouse with the books."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal

from modern_gl.desktop.preferences import STOCK_STATEMENT_VIEW
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.stock_reports.common import INDENT, quantity_column, view_switch
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import money
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.inventory import (
    BY_ITEM,
    BY_WAREHOUSE,
    StatementRow,
    StockStatement,
    stock_statement,
)

VIEW_SETTING = STOCK_STATEMENT_VIEW
GROUPS = (
    (N_("Начало"), "opening"),
    (N_("Приход"), "in"),
    (N_("Расход"), "out"),
    (N_("Конец"), "closing"),
)


class StockStatementPage(ReportPage):
    key = ("stock_statement",)
    has_book = False  # the warehouse keeps one book
    open_stock_card = Signal(int, int, object)  # item, warehouse (0 — all), ReportParams

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Ведомость по складу"), params)
        switch, self.view = view_switch(
            VIEW_SETTING,
            [(BY_ITEM, N_("По товарам")), (BY_WAREHOUSE, N_("По складам"))],
            self.refresh,
        )
        self.add_to_bar(switch)
        self.empty.say(
            tr("Нет движений"),
            tr("За период на складе ничего не было: выберите другой период."),
        )
        self.refresh()

    def title(self) -> str:
        return tr("Ведомость по складу")

    def job(self) -> Callable[[Connection], StockStatement]:
        cid, p, by = self.s.company_id, self.params, self.view()
        return lambda conn: stock_statement(conn, cid, p.date_from, p.date_to, by)

    def fetch(self, conn: Connection) -> StockStatement:
        return self.job()(conn)

    def present(self, data: StockStatement) -> None:
        by_item = self.view() == BY_ITEM
        columns = [
            Column(tr("Товар") if by_item else tr("Склад"), self._name),
            Column(tr("Ед."), lambda r: r.unit_code),
        ]
        for group, side in GROUPS:
            columns += [
                quantity_column(
                    tr("Кол-во"), lambda r, s=side: getattr(r, f"{s}_quantity"), tr(group)
                ),
                Column(
                    tr("Сумма"),
                    lambda r, s=side: getattr(r, f"{s}_amount"),
                    money=True,
                    group=tr(group),
                ),
            ]
        total = data.total
        total.name = tr("Итого")
        self.model.set(
            columns,
            [*data.rows, total] if data.rows else [],
            emphasis=lambda r: r.is_total or (r.depth == 0 and not by_item),
            muted=lambda r: r.depth > 0,
            total=lambda r: r.is_total,
        )
        self._say_books(data)

    @staticmethod
    def _name(row: StatementRow) -> str:
        return INDENT + row.name if row.depth else row.name

    def _say_books(self, data: StockStatement) -> None:
        """The check line: the warehouse's value against the stock accounts of the books
        (not in a warehouse-only company: its books are not shown, D90)."""
        if data.books_amount is None or self.s.stock_only:
            self.footer.setText(tr("Двойной щелчок — карточка товара"))
            self.footer.setStyleSheet("")
            return
        stock = data.total.closing_amount
        if stock == data.books_amount:
            text = tr("Склад сходится со счетами товаров в книге: {sum}  ✓", sum=money(stock))
        else:
            text = tr(
                "Склад {stock}, на счетах товаров в книге {books}: разница {diff} — "
                "проводки на этих счетах не из склада",
                stock=money(stock),
                books=money(data.books_amount),
                diff=money(data.books_amount - stock),
            )
        self.footer.setText(text + "      " + tr("Двойной щелчок — карточка товара"))
        self.footer.setStyleSheet("" if stock == data.books_amount else f"color: {P.red};")

    def drill(self, row: StatementRow | None) -> None:
        if row is not None and row.item_id is not None:
            self.open_stock_card.emit(row.item_id, row.warehouse_id or 0, self.params)
