"""Ctrl+K (D86): one window to find and do anything — commands, places, reports, accounts,
counterparties, documents. Type a few letters (ş = s, ə = e: `fold`), ↑↓, Enter; Esc closes.

What is offered comes from the window (`main_window/commands.py`) for each query.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop import icons
from modern_gl.desktop.theme import P, fonts
from modern_gl.i18n import fold, tr, upper

WIDTH = 620
TOP = 90  # off the window's top edge
SHOWN_ROWS = 11
ENTRY_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class Entry:
    group: str  # translated: «Команды», «Счета»…
    title: str
    run: Callable[[], None]
    hint: str = ""  # on the right: a shortcut, a date
    icon: str = "command"
    words: str = ""  # more to be found by (a code, a VÖEN); the title is always searched


def matches(entry: Entry, query: str) -> bool:
    """Every word typed is in the title or the words, letters folded."""
    text = fold(f"{entry.title} {entry.words}")
    return all(word in text for word in fold(query).split())


class HintDelegate(QStyledItemDelegate):
    """The entry's hint (a shortcut, a date) quietly at the right of its row."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        entry = index.data(ENTRY_ROLE)
        if not isinstance(entry, Entry) or not entry.hint:
            return
        painter.save()
        painter.setFont(fonts().small)
        painter.setPen(QColor(P.tertiary))
        rect = option.rect.adjusted(0, 0, -12, 0)
        align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, int(align), entry.hint)
        painter.restore()


class CommandPalette(QDialog):
    def __init__(self, parent: QWidget, entries: Callable[[str], list[Entry]]) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.setObjectName("palette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._entries = entries
        self.setFixedWidth(WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("paletteSearch")
        self.search.setPlaceholderText(tr("Команда, счёт, контрагент, № документа…"))
        self.search.addAction(
            icons.icon("search", P.tertiary), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        line = QFrame()
        line.setObjectName("hairline")
        line.setFixedHeight(1)
        lay.addWidget(line)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setFont(fonts().body)
        self.list.setIconSize(QSize(16, 16))
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._clicked)
        self.list.setItemDelegate(HintDelegate(self.list))
        lay.addWidget(self.list)
        self.refresh("")

    def open(self) -> None:  # type: ignore[override]
        parent = self.parentWidget()
        if parent is not None:
            top_left = parent.mapToGlobal(parent.rect().topLeft())
            self.move(top_left.x() + (parent.width() - WIDTH) // 2, top_left.y() + TOP)
        self.show()
        self.search.setFocus()

    # ---- the list --------------------------------------------------------------------

    def refresh(self, query: str) -> None:
        self.list.clear()
        group = None
        for entry in self._entries(query):
            if entry.group != group:
                group = entry.group
                self._add_heading(group)
            self._add_entry(entry)
        self._select(self._rows()[0] if self._rows() else -1)
        # as tall as its rows, up to SHOWN_ROWS: no empty sheet under a few results
        height = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        self.list.setFixedHeight(min(max(height, 32), 32 * SHOWN_ROWS) + 4)
        self.adjustSize()

    def _add_heading(self, title: str) -> None:
        item = QListWidgetItem(upper(title))
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setFont(fonts().caption)
        item.setSizeHint(QSize(0, 28))
        self.list.addItem(item)

    def _add_entry(self, entry: Entry) -> None:
        item = QListWidgetItem(icons.icon(entry.icon, P.secondary, 16, P.accent), entry.title)
        item.setData(ENTRY_ROLE, entry)
        item.setSizeHint(QSize(0, 32))
        self.list.addItem(item)

    def _rows(self) -> list[int]:
        """The rows that can be chosen (not the group headings)."""
        return [i for i in range(self.list.count()) if self.list.item(i).data(ENTRY_ROLE)]

    def _select(self, row: int) -> None:
        self.list.setCurrentRow(row)
        if row >= 0:
            self.list.scrollToItem(self.list.item(row))

    def entries_shown(self) -> list[Entry]:
        return [self.list.item(i).data(ENTRY_ROLE) for i in self._rows()]

    def current_entry(self) -> Entry | None:
        item = self.list.currentItem()
        return item.data(ENTRY_ROLE) if item is not None else None

    # ---- keys ------------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """The cursor stays in the search: ↑↓ move in the list, Enter runs, Esc closes."""
        pressed = isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress
        if watched is self.search and pressed and self.key(cast(QKeyEvent, event).key()):
            return True
        return super().eventFilter(watched, event)

    def key(self, key: int) -> bool:
        """A key of the palette; True if it was used."""
        rows = self._rows()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            if rows:
                here = self.list.currentRow()
                at = rows.index(here) if here in rows else 0
                step = 1 if key == Qt.Key.Key_Down else -1
                self._select(rows[(at + step) % len(rows)])
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_current()
            return True
        if key == Qt.Key.Key_Escape:
            self.close()
            return True
        return False

    def _clicked(self, item: QListWidgetItem) -> None:
        if item.data(ENTRY_ROLE):
            self.list.setCurrentItem(item)
            self.run_current()

    def run_current(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        self.close()
        entry.run()
