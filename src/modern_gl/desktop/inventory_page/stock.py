"""The stock list: balances by item and warehouse, and what is set up for them."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QInputDialog,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
)

from modern_gl.application.inventory import QUANTITY_FACTOR, format_quantity
from modern_gl.desktop.inventory_page.dialogs import (
    InventorySettingsDialog,
    ItemDialog,
    open_item,
)
from modern_gl.desktop.inventory_page.form import InventoryForm
from modern_gl.desktop.inventory_page.movements import source_text
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.widgets import EmptyState, money, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    StockBalance,
    code_label,
    has_units,
    last_receipts,
    stock_balances,
)


def row_key(row: StockBalance) -> tuple[int, int]:
    return row.item_id, row.warehouse_id


@dataclass(frozen=True)
class StockGroup:
    """A group header in the stock list: the group and the value of what it holds."""

    name: str
    amount: int


class StockPart(InventoryForm):
    def _build_stock(self, root: QVBoxLayout) -> None:
        self.model = ReportModel()
        self.table = QTableView()
        self.table.setObjectName("list")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.doubleClicked.connect(  # the item: its name, group, unit, account
            lambda index: self.edit_item(index.data(Qt.ItemDataRole.UserRole))
        )
        self.empty = EmptyState(
            "□",
            tr("На складе пока пусто"),
            tr("Добавьте товар и склад, затем введите покупку кнопкой «+ Покупка»."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 2)
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self._show_movements())

    def focus_table(self) -> None:
        self.table.setFocus()

    def chosen_balance(self) -> StockBalance | None:
        """The stock row the movements are of; a group header or nothing — none."""
        index = self.table.currentIndex()
        row = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        return row if isinstance(row, StockBalance) else None

    def refresh(self) -> None:
        chosen = self.chosen_balance()
        balances = stock_balances(self.s.conn, self.s.company_id)
        sources = last_receipts(self.s.conn, self.s.company_id)
        rows: list[StockBalance | StockGroup] = []
        if any(b.group for b in balances):  # each group under its header with its value
            for group, members in groupby(balances, key=lambda b: b.group):
                members = list(members)
                rows.append(StockGroup(group or tr("Без группы"), sum(b.amount for b in members)))
                rows.extend(members)
        else:
            rows = list(balances)

        def average(row) -> int:
            if isinstance(row, StockGroup) or not row.quantity:
                return 0
            numerator = row.amount * QUANTITY_FACTOR
            quotient, remainder = divmod(numerator, row.quantity)
            return quotient + int(remainder * 2 >= row.quantity)

        def source(row) -> str:
            """Where the goods last came from: «İdxal · YGB 12345 · 12.03.2026»."""
            last = None if isinstance(row, StockGroup) else sources.get(row_key(row))
            if last is None:
                return ""
            return f"{source_text(last.source, counterparty=False)} · {ru_date(last.doc_date)}"

        self.model.set(
            [
                Column(
                    tr("Товар"),
                    lambda row: (
                        row.name
                        if isinstance(row, StockGroup)
                        else code_label(row.item_code, row.item_name)
                    ),
                    width=240,
                ),
                Column(tr("Склад"), lambda row: getattr(row, "warehouse_name", ""), width=170),
                Column(tr("Источник"), lambda row: source(row), width=250),
                Column(
                    tr("Количество"),
                    lambda row: (
                        ""
                        if isinstance(row, StockGroup)
                        else format_quantity(row.quantity, row.precision)
                    ),
                    width=130,
                ),
                Column(tr("Ед."), lambda row: getattr(row, "unit_code", ""), width=80),
                Column(tr("Средняя цена"), average, money=True, width=130),
                Column(tr("Стоимость"), lambda row: row.amount, money=True, width=150),
            ],
            rows,
            emphasis=lambda row: isinstance(row, StockGroup),
            section=lambda row: isinstance(row, StockGroup),
        )
        header = self.table.horizontalHeader()
        for index, column in enumerate(self.model.columns):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            if column.width:
                self.table.setColumnWidth(index, column.width)
        header.setStretchLastSection(True)
        self.stack.setCurrentWidget(self.table if rows else self.empty)
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
        if not has_units(self.s.conn, self.s.company_id):
            self.s.notify(tr("Сначала добавьте единицу измерения"))
            return
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
