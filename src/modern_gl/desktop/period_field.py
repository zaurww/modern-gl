"""The period of a report in one field (D105, D129): a capsule «‹ Октябрь 2026 › 📅»; type
«пм», «кв3», «сг», «окт 25» or «1.10-15.10» and Enter (or Tab) — the period is that;
‹ › and the arrow keys ↑ ↓ move to the period before or after; the calendar opens the
period with the mouse (`period_window`). One Tab stop for the whole period, the same on
every report and in the portal's windows — there with their own usual periods and ended
at today (`last`)."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from modern_gl.desktop.period_window import PeriodWindow, Preset, portal_presets
from modern_gl.desktop.widgets import icon_button
from modern_gl.domain.period_input import Period, describe, parse_period, shift
from modern_gl.domain.periods import MONTH, span_period, up_to
from modern_gl.i18n import tr

HINT = "пм · кв3 · сг · окт · 2026 · 1.10-15.10"


class PeriodField(QWidget):
    changed = Signal()

    def __init__(
        self,
        period: Period,
        today: date,
        parent: QWidget | None = None,
        presets: list[Preset] | None = None,  # the window's usual periods; None: a report's
        last: date | None = None,  # no period goes past it: «this month» is to `last`
    ) -> None:
        super().__init__(parent)
        self.today = today
        self.presets, self.last = presets, last
        self._period = period  # as chosen: ‹ › step from a whole month, not from its days
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.capsule = QFrame()
        self.capsule.setObjectName("periodField")
        outer.addWidget(self.capsule)
        row = QHBoxLayout(self.capsule)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setObjectName("period")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setFixedWidth(176)
        self.edit.setToolTip(tr("Период: {hint}", hint=HINT))
        self.edit.setPlaceholderText(HINT)
        self.edit.installEventFilter(self)
        self.edit.editingFinished.connect(self._typed)
        self.edit.textEdited.connect(lambda _text: self._mark(False))
        self.back = capsule_button("previous", tr("Предыдущий период  ↑"))
        self.forward = capsule_button("next", tr("Следующий период  ↓"))
        self.menu_button = capsule_button("calendar", tr("Выбрать период"))
        self.back.clicked.connect(lambda: self.step(-1))
        self.forward.clicked.connect(lambda: self.step(1))
        self.menu_button.clicked.connect(self.show_presets)
        divider = QFrame()
        divider.setObjectName("periodDivider")
        divider.setFixedSize(1, 18)
        row.addWidget(self.back)
        row.addWidget(self.edit)
        row.addWidget(self.forward)
        row.addSpacing(3)
        row.addWidget(divider)
        row.addSpacing(3)
        row.addWidget(self.menu_button)
        # its own width: in a window's wide column the buttons stay by the field
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._show()

    def period(self) -> Period:
        return self._period if self.last is None else up_to(self._period, self.last)

    def set_period(self, first: date, last: date) -> None:
        self._set((first, last))

    def step(self, steps: int) -> None:
        self._set(shift(self._period, steps))

    def show_presets(self) -> None:
        """▾: the period with the mouse — the usual ones, months, quarters, dates."""
        window = PeriodWindow(self._period, self.today, self, self.presets, self.period())
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
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            focused = event.type() == QEvent.Type.FocusIn
            if focused:
                self.edit.selectAll()
            self._restyle("focused", focused)  # the whole capsule is the field
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
        self.edit.setText(describe(self.period()))
        self.edit.setModified(False)
        self._mark(False)
        first, last = self.period()
        self.edit.setToolTip(
            f"{first:%d.%m.%Y} — {last:%d.%m.%Y}\n" + tr("Период: {hint}", hint=HINT)
        )

    def _mark(self, wrong: bool) -> None:
        self.edit.setProperty("invalid", wrong)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        self._restyle("invalid", wrong)

    def _restyle(self, name: str, on: bool) -> None:
        if self.capsule.property(name) == on:
            return
        self.capsule.setProperty(name, on)
        self.capsule.style().unpolish(self.capsule)
        self.capsule.style().polish(self.capsule)


def capsule_button(name: str, tooltip: str) -> QPushButton:
    """A small icon inside the capsule; one Tab stop for the whole period: the field."""
    b = icon_button(name, tooltip)
    b.setObjectName("capsule")
    b.setIconSize(QSize(16, 16))
    b.setFixedSize(28, 28)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def portal_period(today: date, span: str = MONTH, last: date | None = None) -> PeriodField:
    """The period of a portal's window (e-qaimə, ƏDV DH): «Вчера», the weeks and months
    at a click, ended at today — the portal has nothing of tomorrow — or at `last`."""
    return PeriodField(
        span_period(span, today), today, presets=portal_presets(today), last=last or today
    )
