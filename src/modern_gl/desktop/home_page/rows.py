"""The lines of «Bu gün»: a heading in the text's color, rows over thin lines, no cards."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.desktop.theme import fonts


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(fonts().heading)
    label.setContentsMargins(0, 18, 0, 6)
    return label


def hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("hairline")
    line.setFixedHeight(1)
    return line


class Line(QFrame):
    """One row: what on the left, a quiet note, the figure on the right; a click opens
    where it is dealt with."""

    def __init__(self, text: str, note: str = "", figure: str = "", tone: str = "") -> None:
        super().__init__()
        self.setObjectName("homeLine")
        self._open: Callable[[], None] | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 9, 2, 9)
        lay.setSpacing(10)
        self.text = QLabel(text)
        lay.addWidget(self.text)
        self.note = QLabel(note)
        self.note.setObjectName("secondary")
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        lay.addLayout(self.buttons)
        self.figure = QLabel(figure)
        self.figure.setFont(fonts().table)  # sums stand in a column: figures of one width
        self.figure.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if tone:
            self.figure.setObjectName(tone)
        lay.addWidget(self.figure)

    def opens(self, slot: Callable[[], None]) -> Line:
        self._open = slot
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        return self

    def add_action(self, widget: QWidget) -> None:
        self.buttons.addWidget(widget)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._open is not None and event.button() == Qt.MouseButton.LeftButton:
            self._open()
        super().mouseReleaseEvent(event)


class Section(QWidget):
    """A heading and its lines, each over a thin line; `empty` when there are none."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.lay.addWidget(heading(title))
        self.lines: list[Line] = []

    def add(self, line: Line) -> Line:
        self.lay.addWidget(hairline())
        self.lay.addWidget(line)
        self.lines.append(line)
        return line

    def empty(self, text: str) -> None:
        line = self.add(Line(""))
        line.text.setText(text)
        line.text.setObjectName("secondary")
