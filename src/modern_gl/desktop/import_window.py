"""One look for every window that loads from outside — e-qaimə and ƏDV DH from the portal,
their reconciliations, a bank's statement files (DESIGN.md §7): top to bottom the title,
what is loaded (portal, account, files), the bar of what to load (the period, the
directions), a warning, the status line, the figures, the rows, and at the bottom the
quiet actions on the left, «Закрыть» and the one blue button of the step on the right."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

MARGINS = (28, 24, 28, 20)
SPACING = 12


def signed(minor: int) -> str:
    """A figure as the reports show it: a negative one in brackets (D52)."""
    return f"({format_minor(-minor)})" if minor < 0 else format_minor(minor)


def say(label: QLabel, text: str, tone: str = "secondary") -> None:
    """A line of the window in its tone: secondary, warning (an amber plate), success,
    negative; hidden when there is nothing to say."""
    label.setText(text)
    label.setVisible(bool(text))
    if label.objectName() != tone:
        label.setObjectName(tone)
        restyle(label)


def restyle(widget: QWidget) -> None:
    """The style read again: the widget's object name changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ImportWindow(QDialog):
    """The skeleton; a window adds its own between the bar and the footer (`root`) and
    closes with `add_footer()`."""

    def __init__(self, parent: QWidget | None, title: str, subtitle: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(*MARGINS)
        self.root.setSpacing(SPACING)
        self.title = QLabel(title)
        self.title.setFont(fonts().title)
        self.root.addWidget(self.title)
        line = QHBoxLayout()
        self.subtitle = QLabel(subtitle)  # the portal's firm, the account
        self.subtitle.setObjectName("secondary")
        line.addWidget(self.subtitle, 1)
        self.subtitle_note = QLabel()  # «Сверено по 20.10.2026»
        self.subtitle_note.setObjectName("secondary")
        line.addWidget(self.subtitle_note)
        self.root.addLayout(line)
        self.bar = QHBoxLayout()  # what to load: no buttons here, they are at the bottom
        self.bar.setSpacing(16)
        self.root.addLayout(self.bar)
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        self.status = QLabel()  # what to do, what is going on, what was found
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        self.footer_left = QHBoxLayout()
        self.footer_right = QHBoxLayout()
        self.close_button = button(tr("Закрыть"), "flat")
        self.close_button.clicked.connect(self.reject)
        self.footer_right.addWidget(self.close_button)

    def add_notes(self) -> None:
        """The warning and the status line: over the figures and the rows."""
        self.root.addWidget(self.warning)
        self.root.addWidget(self.status)

    def primary(self, text: str, slot=None) -> QPushButton:
        """A blue button of a step, bottom right; the window shows one at a time (D86)."""
        b = button(text, "primary")
        if slot is not None:
            b.clicked.connect(slot)
        b.installEventFilter(self)
        self.footer_right.addWidget(b)
        return b

    def quiet(self, text: str, slot, right: bool = False) -> QPushButton:
        """A quiet action: bottom left, or right before the blue one."""
        b = button(text, "flat")
        b.clicked.connect(slot)
        (self.footer_right if right else self.footer_left).addWidget(b)
        return b

    def add_footer(self) -> None:
        footer = QHBoxLayout()
        footer.addLayout(self.footer_left)
        footer.addStretch(1)
        footer.addLayout(self.footer_right)
        self.root.addLayout(footer)

    def eventFilter(self, watched, event) -> bool:
        """A step's blue button, once shown, has the focus: Enter does it, and the
        period's text is not left selected as if being typed."""
        if event.type() == QEvent.Type.Show and isinstance(watched, QPushButton):
            watched.setDefault(True)
            watched.setFocus()
        return super().eventFilter(watched, event)


class FiguresGrid(QWidget):
    """The answer of a reconciliation (Jon Moon): the verdict, then the portal and the
    books side by side with the difference — red where they differ, empty where not."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.verdict = QLabel()
        self.verdict.setFont(fonts().heading)
        box.addWidget(self.verdict)
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(4)
        for column, caption in enumerate(columns, 1):
            label = QLabel(caption)
            label.setObjectName("secondary")
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, 0, column)
        self.cells: dict[tuple[int, int], QLabel] = {}
        for r, side in enumerate((tr("Портал"), tr("Программа"), tr("Разница")), 1):
            caption = QLabel(side)
            caption.setObjectName("secondary")
            grid.addWidget(caption, r, 0)
            for column in range(1, len(columns) + 1):
                cell = QLabel()
                font = QFont(fonts().table)
                if r == 3:  # the difference: what to look at
                    font.setWeight(QFont.Weight.DemiBold)
                cell.setFont(font)
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                cell.setMinimumWidth(96)
                grid.addWidget(cell, r, column)
                self.cells[(r, column)] = cell
        grid.setColumnStretch(len(columns) + 1, 1)
        box.addLayout(grid)

    def show_figures(self, verdict: str, agrees: bool, portal: list[int], books: list[int]):
        """The figures in minor units; the difference is counted here."""
        say(self.verdict, verdict, "success" if agrees else "")
        for column, (theirs, ours) in enumerate(zip(portal, books, strict=True), 1):
            self.cells[(1, column)].setText(signed(theirs))
            self.cells[(2, column)].setText(signed(ours))
            cell = self.cells[(3, column)]
            say(cell, signed(theirs - ours) if theirs != ours else "", "negative")
            cell.show()  # an empty cell keeps its place in the grid
