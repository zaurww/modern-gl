"""Qt widgets the tests reach for, typed for pyright: each helper checks what Qt types as
optional or as a base class (the focus widget, a completer's list, a table's cell)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QStringListModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QLayout,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)


def running_app() -> QApplication:
    """The QApplication pytest-qt made (`qapp`); `QApplication.instance()` is typed as an
    optional QCoreApplication, the theme and the texts need the widget application."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    return app


def focused[W: QWidget](kind: type[W]) -> W:
    """The widget with keyboard focus, checked to be the `kind` the test expects (a cell
    editor is a QLineEdit, a list a QListView...)."""
    widget = QApplication.focusWidget()
    assert isinstance(widget, kind), widget
    return widget


def completer_of(editor: QWidget) -> QCompleter:
    """The list (QCompleter) a cell editor offers while typing."""
    completer = editor.findChild(QCompleter)
    assert completer is not None
    return completer


def completions(completer: QCompleter) -> list[str]:
    """What the list offers now; cell lists keep their lines in a QStringListModel."""
    model = completer.model()
    assert isinstance(model, QStringListModel)
    return model.stringList()


def popup_of(completer: QCompleter) -> QAbstractItemView:
    """The open list of a completer (Qt types it as optional; a completer always has one)."""
    popup = completer.popup()
    assert popup is not None
    return popup


def cell_editor(table: QAbstractItemView, index: QModelIndex) -> QLineEdit:
    """The open editor of a table cell — a line edit in every entry table."""
    editor = table.indexWidget(index)
    assert isinstance(editor, QLineEdit), editor
    return editor


def tree_item(tree: QTreeWidget, row: int) -> QTreeWidgetItem:
    """A top-level line of a tree list that has it."""
    item = tree.topLevelItem(row)
    assert item is not None, row
    return item


def table_item(table: QTableWidget, row: int, column: int) -> QTableWidgetItem:
    """A filled cell of a table widget."""
    item = table.item(row, column)
    assert item is not None, (row, column)
    return item


def layout_widget(layout: QLayout, n: int) -> QWidget:
    """The widget at place `n` of a layout (not a spacer)."""
    item = layout.itemAt(n)
    widget = item.widget() if item is not None else None
    assert widget is not None, n
    return widget
