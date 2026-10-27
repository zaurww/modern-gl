"""A report on the page «Отчёты»: its icon, name and one grey line of what it shows; a
star to pin it to the sidebar. No borders — the tile is only lit under the mouse or the
keyboard's cursor, as a row in Things."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QWidget

from modern_gl.desktop import icons
from modern_gl.desktop.reports_hub.catalog import Report
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import button, caption
from modern_gl.i18n import tr

ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
ICON = 20


class ReportTile(QFrame):
    opened = Signal(str)  # the report's id
    pin_toggled = Signal(str, bool)  # the id, pinned now

    def __init__(self, report: Report, pinned: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.pinned = pinned
        self.matched = True  # found by the page's search
        self.setObjectName("reportTile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 8, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        mark = QLabel()
        mark.setPixmap(icons.icon(report.icon, P.secondary, ICON).pixmap(ICON, ICON))
        mark.setAlignment(Qt.AlignmentFlag.AlignTop)
        mark.setContentsMargins(0, 1, 0, 0)
        grid.addWidget(mark, 0, 0, 2, 1)
        self.name = QLabel(tr(report.title))
        self.name.setFont(fonts().bold)
        self.name.setWordWrap(True)  # «Satışların portalla üzləşdirilməsi» is long
        grid.addWidget(self.name, 0, 1)
        self.hint = caption(tr(report.hint))
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)
        grid.addWidget(self.hint, 1, 1, 1, 2)
        self.star = button("", "more")
        self.star.setIconSize(QSize(16, 16))
        self.star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.star.clicked.connect(lambda _=False: self.toggle_pin())
        policy = self.star.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # the name does not move when it shows
        self.star.setSizePolicy(policy)
        grid.addWidget(self.star, 0, 2, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)  # a tile beside a taller one: the room goes below
        self.show_star()

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        self.show_star()
        self.pin_toggled.emit(self.report.id, self.pinned)

    def show_star(self, lit: bool = False) -> None:
        """A pinned report's star is always there, filled; the others' — only under the
        mouse or the cursor, so twelve grey stars do not crowd the page."""
        name, color = ("pinned", P.amber) if self.pinned else ("star", P.tertiary)
        self.star.setIcon(icons.icon(name, color, 16))
        self.star.setToolTip(
            tr("Убрать из боковой панели") if self.pinned else tr("Закрепить в боковой панели")
        )
        self.star.setVisible(self.pinned or lit or self.hasFocus())

    def enterEvent(self, event) -> None:
        self.show_star(lit=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.show_star()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.show_star(lit=True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.show_star(lit=self.underMouse())
        super().focusOutEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.opened.emit(self.report.id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in ENTER and not event.modifiers():
            self.opened.emit(self.report.id)
            return
        if event.text() == "*":  # the star from the keyboard
            self.toggle_pin()
            return
        super().keyPressEvent(event)
