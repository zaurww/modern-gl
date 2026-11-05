"""The cell editor and the table both lists use."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
)

from modern_gl.desktop.cell_editing import (
    TABS,
    CellEditor,
    attach_account_list,
    attach_list,
    edit_current,
    holds_on_group,
    tabbed_in,
)
from modern_gl.desktop.landed_cost_page.columns import (
    ACCOUNT,
    COST_TYPE,
    NUMBER_KEYS,
    SC1,
    SC2,
    SC3,
)
from modern_gl.desktop.landed_cost_page.models import ChargesModel, TargetsModel
from modern_gl.desktop.widgets import (
    CutCellTips,
)
from modern_gl.domain.errors import LedgerError


class CellDelegate(QStyledItemDelegate):
    """A line editor with a list for directory cells; Enter or Tab commits and moves on."""

    error = Signal(str)
    # (kind_id, name, owner_id) -> the new element's id: a subconto list offers
    # "+ Добавить «…»", as in the journal (see `attach_list`)
    add_value: Callable[[int, str, int | None], int] | None = None
    # name -> the new cost type's id: «Статья» offers "+ Добавить «…»" too
    add_cost_type: Callable[[str], int] | None = None

    def createEditor(self, parent, option, index):
        model = index.model()
        key = model.key(index)
        editor = CellEditor(parent)
        editor.setFrame(False)
        choices = model.choices(index.row(), key)
        if choices is not None and key == ACCOUNT:
            labels = [label for _, label in choices]
            attach_account_list(editor, labels, model.s.catalog, self._chosen)
        elif choices is not None:
            can_add = (
                self.add_value is not None
                if key in {SC1, SC2, SC3}
                else key == COST_TYPE and self.add_cost_type is not None
            )
            labels = [label for _, label in choices]
            attach_list(editor, labels, True, self._chosen, can_add=can_add)
        elif key in NUMBER_KEYS:
            editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        editor.returnPressed.connect(lambda widget=editor: self._commit_and_next(widget))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        key, text = model.key(index), editor.text().strip()
        kind = model.kind_at(index.row(), key) if key in {SC1, SC2, SC3} else None
        if editor.property("gl_add") and self.add_value is not None and kind is not None:
            model.setData(index, self.add_value(kind, text, model.owner_at(index.row(), key)))
            return
        try:
            if editor.property("gl_add") and key == COST_TYPE and self.add_cost_type is not None:
                model.setData(index, self.add_cost_type(text))
                return
            value = model.parse(index.row(), model.key(index), editor.text())
            model.setData(index, value)
        except (LedgerError, LookupError, ValueError, ArithmeticError) as exc:
            self.error.emit(str(exc).strip("'\""))

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
        ):
            self._commit_and_next(editor)  # Tab as Enter: a group holds the cell
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backtab:
            self._commit_and_next(editor, QAbstractItemDelegate.EndEditHint.EditPreviousItem)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor, hint=QAbstractItemDelegate.EndEditHint.EditNextItem) -> None:
        if editor.property("done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("done", True)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, hint)


class LinesTable(QTableView):
    def __init__(self, model: QAbstractTableModel, delegate: CellDelegate) -> None:
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.setShowGrid(False)
        self.setWordWrap(False)
        CutCellTips(self)
        self.setTabKeyNavigation(True)
        self.verticalHeader().setDefaultSectionSize(34)

    def set_widths(self, widths: dict[str, int], stretch: str) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        model = cast(ChargesModel | TargetsModel, self.model())
        for column, key in enumerate(model.columns):
            self.setColumnWidth(column, widths.get(key, 120))
            if key == stretch:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            index = self.currentIndex()
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEditable:
                self.edit(index)
                return
        super().keyPressEvent(event)
        if event.key() in TABS:  # Tab moves on as Enter does: into the next cell, open
            edit_current(self)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if tabbed_in(event):
            edit_current(self)
