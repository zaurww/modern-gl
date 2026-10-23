"""The period of a report in one field (D105): it reads «Октябрь 2026»; type «пм», «кв3»,
«сг», «окт 25» or «1.10-15.10» and Enter (or Tab) — the period is that; ‹ › and the
arrow keys ↑ ↓ move to the period before or after; ▾ opens the period with the mouse
(`period_window`). One Tab stop for the whole period, the same on every report."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from modern_gl.desktop.period_window import PeriodWindow
from modern_gl.desktop.widgets import icon_button
from modern_gl.domain.period_input import Period, describe, parse_period, shift
from modern_gl.i18n import tr

HINT = "пм · кв3 · сг · окт · 2026 · 1.10-15.10"


class PeriodField(QWidget):
    changed = Signal()

    def __init__(self, period: Period, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.today = today
        self._period = period
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.edit = QLineEdit()
        self.edit.setObjectName("period")
        self.edit.setFixedWidth(210)
        self.edit.setToolTip(tr("Период: {hint}", hint=HINT))
        self.edit.setPlaceholderText(HINT)
        self.edit.installEventFilter(self)
        self.edit.editingFinished.connect(self._typed)
        self.edit.textEdited.connect(lambda _text: self._mark(False))
        self.back = icon_button("back", tr("Предыдущий период  ↑"))
        self.forward = icon_button("forward", tr("Следующий период  ↓"))
        self.menu_button = icon_button("down", tr("Выбрать период"))
        for b in (self.back, self.forward, self.menu_button):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # one Tab stop: the field
        self.back.clicked.connect(lambda: self.step(-1))
        self.forward.clicked.connect(lambda: self.step(1))
        self.menu_button.clicked.connect(self.show_presets)
        for w in (self.edit, self.menu_button, self.back, self.forward):
            row.addWidget(w)
        self._show()

    def period(self) -> Period:
        return self._period

    def set_period(self, first: date, last: date) -> None:
        self._set((first, last))

    def step(self, steps: int) -> None:
        self._set(shift(self._period, steps))

    def show_presets(self) -> None:
        """▾: the period with the mouse — the usual ones, months, quarters, dates."""
        window = PeriodWindow(self._period, self.today, self)
        window.chosen.connect(self._set)
        window.open_under(self.edit)
        self.window_shown = window  # tests reach the open panel

    # ---- the parts -----------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self.edit:
            return False
        enter = isinstance(event, QKeyEvent) and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        )
        if event.type() == QEvent.Type.ShortcutOverride and enter:
            event.accept()  # Enter takes the period, it does not open a row of the report
            return True
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._typed()
                self.step(-1 if key == Qt.Key.Key_Up else 1)
                return True
            if key == Qt.Key.Key_Escape and self.edit.isModified():
                self._show()  # what was typed is dropped
                return True
        if event.type() == QEvent.Type.FocusIn:
            self.edit.selectAll()
        return False

    def _typed(self) -> None:
        if not self.edit.isModified():
            return
        period = parse_period(self.edit.text(), self.today)
        if period is None:
            self._mark(True)  # not understood: said so, the period stays as it was
            return
        self._set(period)

    def _set(self, period: Period) -> None:
        changed = period != self._period
        self._period = period
        self._show()
        if changed:
            self.changed.emit()

    def _show(self) -> None:
        self.edit.setText(describe(self._period))
        self.edit.setModified(False)
        self._mark(False)
        first, last = self._period
        self.edit.setToolTip(
            f"{first:%d.%m.%Y} — {last:%d.%m.%Y}\n" + tr("Период: {hint}", hint=HINT)
        )

    def _mark(self, wrong: bool) -> None:
        self.edit.setProperty("invalid", wrong)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
