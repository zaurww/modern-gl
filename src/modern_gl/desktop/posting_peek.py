"""F7 on a row of a list (the journal, a bank statement, purchases and sales, the
warehouse's documents): its postings in a window under the row, without opening the
document — as Quick Look does. Esc, F7 or a click elsewhere closes it. Not in «only the
warehouse» (D90)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QFrame, QLabel, QVBoxLayout

from modern_gl.application.posting_preview import PreviewPosting
from modern_gl.desktop.posting_preview import postings_columns
from modern_gl.desktop.reports_page.report_table import ReportTable
from modern_gl.desktop.reports_page.table import ROW_HEIGHT, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import KEYS, bind
from modern_gl.desktop.widgets import caption
from modern_gl.i18n import tr

SHOWN_ROWS = 12
WIDTH = 900  # px at most: as wide as the list under it otherwise

# the row under the cursor: its postings, or None when it has none to show (a heading,
# an account of the bank)
Read = Callable[[], list[PreviewPosting] | None]


class PostingsPeek(QFrame):
    """A popup: «Проводки» and the table, as under a document's form."""

    def __init__(self, parent: QAbstractItemView, postings: list[PreviewPosting]) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("postingsWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(8)
        title = QLabel(tr("Проводки"))
        title.setObjectName("postingsTitle")
        root.addWidget(title)
        if not postings:
            root.addWidget(caption(tr("проводок нет")))
            return
        self.model = ReportModel()
        self.model.bands = False
        self.model.set(postings_columns(postings), postings)
        self.table = ReportTable(self.model)
        self.table.layout_columns()
        head = self.table.horizontalHeader()
        self.table.setFixedHeight(
            head.sizeHint().height() + min(len(postings), SHOWN_ROWS) * ROW_HEIGHT + 2
        )
        self.table.setFixedWidth(min(WIDTH, sum(self.table.widths.values()) + 4))
        root.addWidget(self.table)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        pressed = QKeySequence(event.keyCombination())
        if any(pressed == QKeySequence(k) for k in KEYS["postings"].keys):  # as it opened
            self.close()
            return
        super().keyPressEvent(event)


def peek(view: QAbstractItemView, postings: list[PreviewPosting]) -> PostingsPeek:
    """Show the postings under the current row of `view`."""
    window = PostingsPeek(view, postings)
    rect = view.visualRect(view.currentIndex())
    at = view.viewport().mapToGlobal(QPoint(12, rect.bottom() + 2))  # under the whole row
    window.adjustSize()
    window.move(at)
    window.show()
    return window


def bind_peek(view: QAbstractItemView, session: Session, read: Read) -> None:
    """F7 on the list shows the postings of its current row."""

    def show() -> None:
        if session.stock_only or not view.currentIndex().isValid():
            return
        if (postings := read()) is not None:
            peek(view, postings)

    bind(view, "postings", show)
