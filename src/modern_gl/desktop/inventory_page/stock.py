"""The stock list: balances by item and warehouse, and what is set up for them."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QStackedLayout,
    QVBoxLayout,
)

from modern_gl.application.inventory import format_quantity, unit_price
from modern_gl.desktop.inventory_page.dialogs import (
    InventorySettingsDialog,
    ItemDialog,
    open_item,
)
from modern_gl.desktop.inventory_page.form import InventoryForm
from modern_gl.desktop.inventory_page.movements import source_text
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.reports_page.report_table import ReportTable, SelectionMode
from modern_gl.desktop.widgets import EmptyState, hide_when_viewing, money, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import fold, sort_key, tr
from modern_gl.reporting.inventory import (
    StockBalance,
    StockSource,
    code_label,
    idle_items,
    item_choices,
    last_receipts,
    stock_balances,
)


def row_key(row: StockBalance) -> tuple[int, int]:
    return row.item_id, row.warehouse_id


def searched(row: StockBalance) -> str:
    """What the search looks in: the item's code and name, the warehouse, the group."""
    return " ".join((row.item_code or "", row.item_name, row.warehouse_name, row.group))


def grouped(balances: list[StockBalance]) -> list[StockBalance | StockGroup]:
    """By group, as the directory shows them (each group under its header with its
    value), the items by name; no groups — the items alone."""
    balances = sorted(
        balances,
        key=lambda b: (b.group == "", sort_key(b.group), sort_key(b.item_name), b.warehouse_name),
    )
    if not any(b.group for b in balances):
        return list(balances)
    rows: list[StockBalance | StockGroup] = []
    for group, grouped in groupby(balances, key=lambda b: b.group):
        members = list(grouped)
        rows.append(StockGroup(group or tr("Без группы"), sum(b.amount for b in members)))
        rows.extend(members)
    return rows


@dataclass(frozen=True)
class StockGroup:
    """A group header in the stock list: the group and the value of what it holds."""

    name: str
    amount: int


class StockPart(InventoryForm):
    def _build_stock(self, root: QVBoxLayout) -> None:
        self.model = ReportModel()
        self.table = ReportTable(self.model, SelectionMode.SingleSelection)  # a report (D127)
        self.table.doubleClicked.connect(  # the item: its name, group, unit, account
            lambda index: self.edit_item(index.data(Qt.ItemDataRole.UserRole))
        )
        self.empty = EmptyState(  # what a beginner does first, right there (D88)
            "□",
            "",
            "",
            (
                (tr("+ Товар"), lambda: self.add_item()),  # noqa: PLW0108 late-bound: a test replaces it
                (tr("+ Покупка"), lambda: self.operation("receipt")),
                (tr("Начальные остатки"), lambda: self.operation("opening")),
            ),
        )
        hide_when_viewing(self.s.read_only, *self.empty.buttons)
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 2)
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self._show_movements())

    def focus_table(self) -> None:
        self.table.setFocus()

    def has_stock(self) -> bool:
        return self.model.rowCount() > 0

    def chosen_balance(self) -> StockBalance | None:
        """The stock row the movements are of; a group header or nothing — none."""
        index = self.table.currentIndex()
        row = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        return row if isinstance(row, StockBalance) else None

    def refresh(self) -> None:
        chosen = self.chosen_balance()
        balances = stock_balances(self.s.conn, self.s.company_id)
        shown = balances + (idle_items(self.s.conn, self.s.company_id) if self.idle_shown() else [])
        needle = fold(self.search.text().strip())
        if needle:
            shown = [b for b in shown if needle in fold(searched(b))]
        rows = grouped(shown)
        self.model.set(
            self._columns(last_receipts(self.s.conn, self.s.company_id)),
            rows,
            emphasis=lambda row: isinstance(row, StockGroup),
            section=lambda row: isinstance(row, StockGroup),
            muted=lambda row: isinstance(row, StockBalance) and not (row.quantity or row.amount),
        )
        self.table.layout_columns()
        self.stack.setCurrentWidget(self.table if rows or needle else self.empty)
        if not rows and not needle:
            self._say_what_next()
        self._choose(chosen)
        self.header.subtitle.setText(
            tr(
                "{items} позиций · {amount}",
                items=len(balances),
                amount=money(sum(r.amount for r in balances), False),
            )
        )
        self._show_movements()
        self._show_documents()

    def _columns(self, sources: dict[tuple[int, int], StockSource]) -> list[Column]:
        def average(row) -> int:
            if isinstance(row, StockGroup):
                return 0
            return unit_price(row.amount, row.quantity) or 0

        def source(row) -> str:
            """Where the goods last came from: «İdxal · YGB 12345 · 12.03.2026»."""
            last = None if isinstance(row, StockGroup) else sources.get(row_key(row))
            if last is None:
                return ""
            return f"{source_text(last.source, counterparty=False)} · {ru_date(last.doc_date)}"

        def quantity(row) -> str:
            if isinstance(row, StockGroup) or not (row.quantity or row.amount):
                return ""
            return format_quantity(row.quantity, row.precision)

        def name(row) -> str:
            if isinstance(row, StockGroup):
                return row.name
            return code_label(row.item_code, row.item_name)

        return [
            Column(tr("Товар"), name, width=240),
            Column(tr("Склад"), lambda row: getattr(row, "warehouse_name", ""), width=170),
            Column(tr("Источник"), source, width=250),
            Column(tr("Количество"), quantity, width=130, right=True),
            Column(tr("Ед."), lambda row: getattr(row, "unit_code", ""), width=80),
            Column(tr("Средняя цена"), average, money=True, width=130),
            Column(tr("Стоимость"), lambda row: row.amount, money=True, width=150),
        ]

    def _say_what_next(self) -> None:
        """No stock: with no item yet — start with one; with items — bring stock in."""
        no_items = not item_choices(self.s.conn, self.s.company_id)
        if no_items:
            self.empty.say(
                tr("На складе пока пусто"),
                tr(
                    "Начните с товара: название и единица — склад появится сам. Или сразу "
                    "покупка: новый товар можно написать прямо в строке."
                ),
            )
        else:
            self.empty.say(
                tr("Остатков пока нет"),
                tr("Введите покупку или начальные остатки — остатки появятся здесь."),
            )
        if not self.s.read_only:
            self.empty.buttons[0].setVisible(no_items)

    def _choose(self, balance: StockBalance | None) -> None:
        """The row chosen before a refresh, chosen again (its quantities may differ now)."""
        if balance is None:
            return
        for index, row in enumerate(self.model.rows):
            if isinstance(row, StockBalance) and row_key(row) == row_key(balance):
                self.table.selectRow(index)
                return

    def add_unit(self) -> None:
        code, ok = QInputDialog.getText(self, tr("Новая единица"), tr("Краткое обозначение:"))
        if not ok or not code.strip():
            return
        name, ok = QInputDialog.getText(self, tr("Новая единица"), tr("Полное название:"))
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_unit(self.s.company_id, code, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Единица «{name}» добавлена", name=name.strip()))

    def add_item(self) -> None:
        dialog = ItemDialog(self.s, self.inventory, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.s.catalog.reload()
            self.s.notify(tr("Товар добавлен"))
            self.refresh()

    def edit_item(self, row) -> None:
        if not isinstance(row, StockBalance):
            return
        self.s.catalog.reload()
        if open_item(self.s, self.inventory, row.item_value_id, self):
            self.refresh()

    def add_warehouse(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Новый склад"), tr("Название склада:"))
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_warehouse(self.s.company_id, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.catalog.reload()
        self.s.notify(tr("Склад «{name}» добавлен", name=name.strip()))
        self.refresh()

    def add_landed_cost_type(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr("Новый вид расходов"),
            tr("Название (например, доставка или таможня):"),
        )
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_landed_cost_type(self.s.company_id, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Вид расходов «{name}» добавлен", name=name.strip()))

    def settings(self) -> None:
        if InventorySettingsDialog(self.s, self).exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Настройки склада сохранены"))
