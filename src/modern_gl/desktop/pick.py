"""A choice typed, not clicked (D49): a field where typing finds the element (by name,
code or VÖEN, `fold`), Enter takes it and goes on to the next field, and a name the
list does not have is reported, so the page can offer to add it there and then.

It keeps `QComboBox`'s interface (`addItem`, `currentData`, `findData`, `activated`…),
so a form of combo boxes turns into one typed from the keyboard without new logic."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QEvent, QModelIndex, QObject, QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QCompleter, QLineEdit, QWidget

from modern_gl.application.catalog import search
from modern_gl.desktop.postings import fit_popup
from modern_gl.i18n import fold

ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
OPEN = (Qt.Key.Key_Down, Qt.Key.Key_F4)


class PickBox(QLineEdit):
    """One of a list of (label, data); nothing chosen until something is."""

    activated = Signal(int)  # chosen by the user (typed, picked, or added)
    unknown = Signal(str)  # typed text names nothing in the list

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._items: list[tuple[str, Any, str]] = []  # list label, data, text in the field
        self._hidden: set[int] = set()
        self._index = -1
        self._held = False  # Enter took nothing: the field keeps the cursor
        self._shown: list[int] = []  # the list's rows → item indexes
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(12)
        self._completer.setWidget(self)  # filtering is ours (search), not Qt's prefix
        self._popup().setObjectName("completer")
        self._popup().installEventFilter(self)  # after QCompleter's filter, so it runs first
        self._completer.activated[QModelIndex].connect(  # pyright: ignore[reportIndexIssue]
            lambda index: self._clicked(index.row())
        )
        self.textEdited.connect(lambda text: self._open(text))
        self.editingFinished.connect(self._typed)

    # ---- QComboBox's interface -------------------------------------------------------

    def addItem(self, text: str, data: object = None, shown: str | None = None) -> None:
        self._items.append((text, data, text if shown is None else shown))

    def clear(self) -> None:
        self._items.clear()
        self._hidden.clear()
        self._set_index(-1)

    def count(self) -> int:
        return len(self._items)

    def findData(self, data: object) -> int:
        return next((i for i, item in enumerate(self._items) if item[1] == data), -1)

    def findText(self, text: str) -> int:
        return next((i for i, item in enumerate(self._items) if text in (item[0], item[2])), -1)

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def isItemHidden(self, index: int) -> bool:
        return index in self._hidden

    def itemData(self, index: int) -> Any:
        return self._items[index][1]

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        self._set_index(index if 0 <= index < len(self._items) else -1)

    def currentData(self) -> Any:
        return self._items[self._index][1] if self._index >= 0 else None

    def currentText(self) -> str:
        return self._items[self._index][0] if self._index >= 0 else ""

    def setItemHidden(self, index: int, hidden: bool) -> None:
        """Not offered (an operation the ƏDV deposit account may not make)."""
        if hidden:
            self._hidden.add(index)
        else:
            self._hidden.discard(index)

    # ---- choosing ----------------------------------------------------------------------

    def _set_index(self, index: int) -> None:
        self._index = index
        self.setText(self._items[index][2] if index >= 0 else "")
        self.setCursorPosition(0)

    def _choose(self, index: int) -> None:
        self._set_index(index)
        self.activated.emit(index)

    def _offered(self) -> list[int]:
        return [i for i in range(len(self._items)) if i not in self._hidden]

    def _popup(self) -> QAbstractItemView:
        # asked anew each time: PySide may drop a kept wrapper of the parentless popup
        return cast(QAbstractItemView, self._completer.popup())

    def _open(self, text: str, everything: bool = False) -> None:
        """The list under the field: what matches the text, or all of it."""
        offered = self._offered()
        labels = [self._items[i][0] for i in offered]
        typed = bool(text.strip()) and not everything
        if not typed and not everything:
            self._popup().hide()
            return
        found = search(labels, text) if typed else labels
        by_label: dict[str, list[int]] = {}
        for i in offered:
            by_label.setdefault(self._items[i][0], []).append(i)
        self._shown = [by_label[label].pop(0) for label in found]
        self._model.setStringList(found)
        popup = self._popup()
        if not found:
            popup.hide()
            return
        rect = self.rect()
        rect.setWidth(max(rect.width(), 320))
        self._completer.complete(rect)
        fit_popup(popup, len(found))
        chosen = self._shown.index(self._index) if self._index in self._shown else 0
        row = 0 if typed else chosen  # the whole list: on what is chosen
        popup.setCurrentIndex(self._model.index(row))

    def _clicked(self, row: int) -> None:
        if 0 <= row < len(self._shown):
            self._choose(self._shown[row])

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """On the open list, Enter or Tab takes the highlighted element and goes on (Qt
        would hand the key to the field first, which would take what was typed)."""
        if watched is self._popup() and event.type() == QEvent.Type.KeyPress:
            key = event.key()  # pyright: ignore[reportAttributeAccessIssue]
            row = self._popup().currentIndex().row()
            if (key in ENTER or key == Qt.Key.Key_Tab) and 0 <= row < len(self._shown):
                self._popup().hide()
                self._choose(self._shown[row])
                self.focusNextChild()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.key() in OPEN and not self._popup().isVisible():
            self._open(self.text(), everything=True)
            return
        if event.key() in ENTER and not event.modifiers():
            self._held = False
            super().keyPressEvent(event)  # editingFinished: what was typed is taken
            if self._held:
                event.accept()  # nothing taken: stay here
            else:
                event.ignore()  # the page moves on to the next field
            return
        super().keyPressEvent(event)

    def _typed(self) -> None:
        """Left (Enter, Tab, a click elsewhere) without picking from the list: the text is
        taken if it names one element; text naming nothing is reported."""
        self._popup().hide()  # left with the list open: what was typed decides
        text = self.text().strip()
        current = self._items[self._index][2] if self._index >= 0 else ""
        if text == current:
            return
        offered = self._offered()
        if not text:
            self._choose(-1)
            return
        needle = fold(text)
        exact = [i for i in offered if needle in (fold(self._items[i][0]), fold(self._items[i][2]))]
        found = search([self._items[i][0] for i in offered], text)
        if exact or len(found) == 1:
            label = found[0] if not exact else None
            index = exact[0] if exact else next(i for i in offered if self._items[i][0] == label)
            self._choose(index)
            return
        self._held = True
        self._set_index(self._index)  # back to what is chosen
        if not found:
            # deferred: a dialog must not open while the field is still finishing
            QTimer.singleShot(0, lambda: self.unknown.emit(text))
