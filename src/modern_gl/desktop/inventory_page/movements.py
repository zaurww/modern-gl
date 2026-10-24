"""The chosen item's movements in its warehouse: where the goods came from and went to."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QStackedWidget,
    QWidget,
)

from modern_gl.application.inventory import INCOMING_REASONS, format_quantity
from modern_gl.desktop.inventory_page.form import InventoryForm
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.reports_page.report_table import ReportTable, SelectionMode
from modern_gl.desktop.widgets import EmptyState, ru_date
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    MovementSource,
    StockCardLine,
    stock_card,
)


def source_text(source: MovementSource, counterparty: bool = True) -> str:
    """«Alış · e-qaimə AA123 · Supplier», «İdxal · YGB 12345», «Yerdəyişmə → Mağaza»."""
    if source.movement_type == "opening":
        parts = [tr("Начальные остатки")]
    elif source.doc_type == "incoming":
        reason = INCOMING_REASONS.get(source.incoming_reason or "")
        parts = [tr("Оприходование"), *([tr(reason[0])] if reason else [])]
    elif source.movement_type == "receipt" and source.invoice_kind == "customs":
        parts = [tr("Импорт · ГТД {n}", n=source.invoice)]
    elif source.movement_type == "receipt":
        parts = [tr("Покупка"), *([f"e-qaimə {source.invoice}"] if source.invoice else [])]
    elif source.doc_type == "sale":
        parts = [tr("Продажа")]
    elif source.movement_type == "transfer_out":
        parts = [tr("Перемещение → {w}", w=source.other_warehouse or "")]
    elif source.movement_type == "transfer_in":
        parts = [tr("Перемещение ← {w}", w=source.other_warehouse or "")]
    elif source.movement_type == "landed_cost":
        parts = [tr("Дополнительные расходы"), *([source.cost_type] if source.cost_type else [])]
    else:  # an issue
        parts = [tr("Списание"), *([source.cost_type] if source.cost_type else [])]
    if counterparty and source.counterparty and source.doc_type in ("receipt", "sale"):
        parts.append(source.counterparty)
    return " · ".join(parts)


class MovementsPart(InventoryForm):
    def _build_movements(self) -> QWidget:
        self.card_model = ReportModel()
        self.card = ReportTable(self.card_model, SelectionMode.SingleSelection)  # as the stock
        self.card.doubleClicked.connect(self._open_movement)
        for keys in ("Return", "Enter"):  # only on the list
            shortcut = QShortcut(QKeySequence(keys), self.card)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda: self._open_movement(self.card.currentIndex()))
        self.card_empty = EmptyState(
            "↕",
            tr("Выберите товар"),
            tr("Здесь будет видно, откуда он пришёл и куда ушёл."),
        )
        self.card_stack = QStackedWidget()
        self.card_stack.addWidget(self.card)
        self.card_stack.addWidget(self.card_empty)
        return self.card_stack

    def _show_movements(self) -> None:
        balance = self.chosen_balance()
        if balance is None:
            self.below_title.setText("")
            if self.has_stock():
                self.card_empty.say(
                    tr("Выберите товар"), tr("Здесь будет видно, откуда он пришёл и куда ушёл.")
                )
            else:  # no stock yet: nothing to choose
                self.card_empty.say(
                    tr("Движений пока нет"),
                    tr("Здесь будет видно, откуда пришёл и куда ушёл каждый товар."),
                )
            self.card_stack.setCurrentWidget(self.card_empty)
            return
        self.below_title.setText(f"{balance.item_name} · {balance.warehouse_name}")
        lines = stock_card(self.s.conn, self.s.company_id, balance.item_id, balance.warehouse_id)

        def quantity(value: int) -> str:
            return format_quantity(value, balance.precision) if value else ""

        self.card_model.set(
            [
                Column(tr("Дата"), lambda line: ru_date(line.doc_date), width=110),
                Column(tr("№"), lambda line: line.number, width=65),
                Column(tr("Откуда / куда"), lambda line: source_text(line.source), width=380),
                Column(
                    tr("Приход"), lambda line: quantity(line.quantity_in), width=110, right=True
                ),
                Column(
                    tr("Расход"), lambda line: quantity(line.quantity_out), width=110, right=True
                ),
                Column(
                    tr("Остаток"),
                    lambda line: quantity(line.quantity_balance),
                    width=110,
                    right=True,
                ),
                Column(
                    tr("Стоимость остатка"),
                    lambda line: line.amount_balance,
                    money=True,
                    width=150,
                ),
            ],
            lines,
        )
        self.card.layout_columns()
        self.card_stack.setCurrentWidget(self.card)
        self.card.scrollToBottom()  # the latest movements, nearest the balance above

    def _open_movement(self, index: QModelIndex) -> None:
        line: StockCardLine | None = (
            index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        )
        if line is not None:
            self.open_inventory_document.emit(line.document_id)
