"""The list table (DESIGN.md §4): documents, elements, rates, templates — rows to open.

The list fills the page: one text column (the memo, the name) takes the free room, the
others are as wide as their text. A double click or Enter opens a row (the bank alone opens it
with one: it is a way through its levels, D132)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QSortFilterProxyModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QTreeWidget

from modern_gl.desktop.reports_page.table import ReportModel

SelectionMode = QAbstractItemView.SelectionMode


class ListTable(QTableView):
    """A read-only list (D86): rows chosen whole, no grid, no row numbers, not edited.
    `fill` — the column that takes the free room; by default the first name column of a
    report model (a column with no width of its own, not an amount), else the last."""

    def __init__(
        self,
        model: QAbstractItemModel | None = None,
        row_height: int = 34,
        *,
        fill: int | None = None,
        wrap: bool = True,
        selection: SelectionMode = SelectionMode.SingleSelection,
    ) -> None:
        super().__init__()
        self.setObjectName("list")
        self.fill = fill
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(selection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(wrap)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(False)
        if model is not None:  # else set once it is made
            self.setModel(model)

    def setModel(self, model: QAbstractItemModel | None) -> None:
        super().setModel(model)
        if model is not None:
            model.modelReset.connect(self.fit_columns)  # new rows or other columns
            self.fit_columns()

    def fill_column(self) -> int:
        model = self.model()
        if self.fill is not None:
            return self.fill
        source = model.sourceModel() if isinstance(model, QSortFilterProxyModel) else model
        if isinstance(source, ReportModel):
            for i, col in enumerate(source.columns):
                if not (col.width or col.money or col.right):
                    return i
        return self.horizontalHeader().count() - 1

    def fit_columns(self) -> None:
        """The fill column stretches; the others fit their text and the caption."""
        hh = self.horizontalHeader()
        if self.model() is None or not hh.count():
            return
        fill = self.fill_column()
        for i in range(hh.count()):
            if i == fill:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.resizeColumnToContents(i)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter opens the row as a double click does (a page's own Enter comes first)."""
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and not event.modifiers() and self.currentIndex().isValid():
            self.doubleClicked.emit(self.currentIndex())
            return
        super().keyPressEvent(event)


def fit_tree(tree: QTreeWidget, *fill: int) -> None:
    """A list with ticks or groups (a QTreeWidget) is as wide as a ListTable: the `fill`
    columns (the names, the long explanations) share the free room, the others follow
    their text."""
    header = tree.header()
    header.setStretchLastSection(False)
    for column in range(tree.columnCount()):
        mode = QHeaderView.ResizeMode
        header.setSectionResizeMode(
            column, mode.Stretch if column in fill else mode.ResizeToContents
        )
