"""A short message at the bottom of the window (D86): what was just done, and «Undo»
where it can be undone. It replaces the status bar."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from modern_gl.i18n import tr

SHOWN_MS = 4000
WITH_UNDO_MS = 7000  # time to read it and change one's mind
FADE_MS = 160
BOTTOM = 28  # off the window's bottom edge


class Toast(QFrame):
    """One at a time: a new message replaces the one shown."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("toast")
        self._undo: Callable[[], None] | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 9, 10, 9)
        lay.setSpacing(14)
        self.label = QLabel()
        self.label.setObjectName("toastText")
        lay.addWidget(self.label)
        self.undo_button = QPushButton(tr("Отменить"))
        self.undo_button.setObjectName("toastAction")
        self.undo_button.clicked.connect(self.run_undo)
        lay.addWidget(self.undo_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        window.installEventFilter(self)
        self.hide()

    def show_message(self, message: str, undo: Callable[[], None] | None = None) -> None:
        self._undo = undo
        self.label.setText(message)
        self.undo_button.setVisible(undo is not None)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(WITH_UNDO_MS if undo else SHOWN_MS)

    def message(self) -> str:
        """The message shown now ("" when none)."""
        return self.label.text() if self.isVisible() else ""

    def run_undo(self) -> None:
        undo, self._undo = self._undo, None
        self.hide()
        if undo is not None:
            undo()

    def _place(self) -> None:
        window = self.parentWidget()
        if window is None:
            return
        width = min(self.sizeHint().width(), window.width() - 40)
        self.resize(width, self.sizeHint().height())
        self.move((window.width() - width) // 2, window.height() - self.height() - BOTTOM)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        return super().eventFilter(watched, event)
