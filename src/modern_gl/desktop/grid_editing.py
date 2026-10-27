"""What every table of entry does with its rows (Ins, F9, Del), in one place: the document,
the warehouse document, the opening balances and the template editor took it from here
instead of four copies. A page says which table and rows (`_grid`, `_rows`) and where the
cursor goes on a new row."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QAbstractItemDelegate, QAbstractItemView, QApplication, QTableView


class EditableRows(Protocol):
    """The rows of an entry table (PostingsModel, InventoryLinesModel…)."""

    @property
    def read_only(self) -> bool: ...

    def insert_row(self, at: int | None = None, /) -> int: ...

    def duplicate_row(self, i: int, /) -> int: ...

    def remove_row(self, i: int, /) -> None: ...


def finish_editing(*tables: QTableView) -> None:
    """Commit and close an open cell editor, so a row action sees what was typed."""
    editor = QApplication.focusWidget()
    for table in tables:
        if table.state() == QAbstractItemView.State.EditingState and editor is not None:
            table.commitData(editor)
            table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)


class GridEditing:
    """Ins — a row under the current one, F9 — its copy, Del — away."""

    INSERT_COLUMN = 0  # where the cursor stands on a new row
    EDIT_INSERTED = False  # the cell opens for typing at once
    DUPLICATE_COLUMN: int | None = None  # on the copy; None — the column it was in

    def _grid(self) -> QTableView:
        raise NotImplementedError

    def _rows(self) -> EditableRows:
        raise NotImplementedError

    def _finish_editing(self) -> None:
        finish_editing(self._grid())

    def _insert_row(self) -> None:
        table, rows = self._grid(), self._rows()
        if rows.read_only:
            return
        self._finish_editing()
        current = table.currentIndex()
        row = rows.insert_row(current.row() + 1 if current.isValid() else None)
        index = table.model().index(row, self.INSERT_COLUMN)
        table.setCurrentIndex(index)
        if self.EDIT_INSERTED:
            table.edit(index)

    def _duplicate_row(self) -> None:
        table, rows = self._grid(), self._rows()
        current = table.currentIndex()
        if rows.read_only or not current.isValid():
            return
        self._finish_editing()
        row = rows.duplicate_row(current.row())
        column = current.column() if self.DUPLICATE_COLUMN is None else self.DUPLICATE_COLUMN
        table.setCurrentIndex(table.model().index(row, column))

    def _remove_row(self) -> None:
        table, rows = self._grid(), self._rows()
        self._finish_editing()
        current = table.currentIndex()
        if rows.read_only or not current.isValid():
            return
        rows.remove_row(current.row())
        row = min(current.row(), table.model().rowCount() - 1)
        table.setCurrentIndex(table.model().index(row, current.column()))
