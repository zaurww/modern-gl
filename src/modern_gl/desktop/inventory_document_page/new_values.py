"""A name typed in a cell that its directory lacks: a new element, item, service or
warehouse, added right from the line."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import (
    QPersistentModelIndex,
    QTimer,
)
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
)

from modern_gl.desktop.cell_editing import edit_again, edit_next
from modern_gl.desktop.inventory_document_page.columns import (
    DOCUMENT_TYPES,
    EXPENSE,
    ITEM,
    MEMO,
    QUANTITY,
)
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.inventory_page import ItemDialog
from modern_gl.desktop.new_cell_value import add_typed_value, ask_add, offer_new_value
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class NewValuesPart(InventoryDocumentForm):
    def _connect_delegate(self) -> None:
        self.delegate.error.connect(self.show_error)
        self.delegate.add_value = partial(add_typed_value, self.s)
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        self.delegate.unknown_value.connect(
            lambda index, kind_id, text: QTimer.singleShot(
                0, lambda: self._create_value(index, kind_id, text)
            )
        )
        self.delegate.unknown_item.connect(
            lambda index, text: QTimer.singleShot(0, lambda: self._create_item(index, text))
        )
        self.delegate.unknown_warehouse.connect(
            lambda index, text, picked: QTimer.singleShot(
                0, lambda: self._create_warehouse(index, text, ask=not picked)
            )
        )

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        offer_new_value(
            self,
            self.s,
            self.table,
            index,
            kind_id,
            text,
            lambda row, column: self.model.owner_at(row, self.model.columns[column]),
        )

    def _create_item(self, index: QPersistentModelIndex, text: str) -> None:
        if not index.isValid():
            return
        if self.doc_type in {"sale", "receipt"}:
            answer = self._service_or_item(text)
            if answer is None:
                edit_again(self.table, index, text)  # the name, to correct it
                return
            if answer == "service":  # what was typed says what the service is
                self._make_service(index.row(), text)
                return
        dialog = ItemDialog(self.s, self.inventory, self, name=text)
        if dialog.units.count() == 0:
            self.show_error(tr("Сначала добавьте единицу измерения"))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.item_id is None:
            edit_again(self.table, index, text)
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), dialog.item_id)
        self.s.notify(tr("Товар добавлен"))
        edit_next(self.table, index)

    def _make_service(self, row: int, text: str) -> None:
        """The line becomes a service with this text; a receipt's goes on to the account the
        service (fixed asset) is charged to."""
        self.model.setData(self.model.index(row, self.model.columns.index(MEMO)), text)
        self.model.setData(self.model.index(row, self.model.columns.index(ITEM)), None)
        self.table.configure_columns()
        key = EXPENSE if self.doc_type == "receipt" else QUANTITY
        index = self.model.index(row, self.model.columns.index(key))
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def _service_or_item(self, text: str) -> str | None:
        """A name the item list does not have: a service (fixed asset), or a new item?"""
        sale = self.doc_type == "sale"
        box = QMessageBox(self)
        box.setWindowTitle(tr(DOCUMENT_TYPES[self.doc_type]))
        box.setText(
            tr("«{text}» нет среди товаров. Это услуга или новый товар?", text=text)
            if sale
            else tr("«{text}» нет среди товаров. Это услуга, ОС или новый товар?", text=text)
        )
        service = box.addButton(
            tr("Услуга") if sale else tr("Услуга, ОС"), QMessageBox.ButtonRole.AcceptRole
        )
        item = box.addButton(tr("Новый товар…"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(service)
        box.exec()
        clicked = box.clickedButton()
        return "service" if clicked is service else "item" if clicked is item else None

    def _create_warehouse(self, index: QPersistentModelIndex, text: str, ask: bool = True) -> None:
        """A warehouse the list lacks; picked as "+ Добавить «…»" it goes in at once."""
        if not index.isValid():
            return
        if ask and not ask_add(self, text, tr("Склад")):
            edit_again(self.table, index, text)
            return
        try:
            warehouse_id = self.inventory.add_warehouse(self.s.company_id, text)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), warehouse_id)
        self.s.notify(tr("Склад «{name}» добавлен", name=text))
        edit_next(self.table, index)
