"""One date in a form (D105): it reads «05.10.2026»; type it short — «5», «5.10»,
«051025», «вчера», «+3» — and Enter or Tab, the same reading as the period of a report;
↑ ↓ move it by a day; the calendar at the right end picks it with the mouse (D129). What is not
understood turns red on Enter and is dropped on Tab: the field always shows the date
that will be saved."""

from __future__ import annotations

from datetime import date
from typing import cast

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop import icons
from modern_gl.desktop.day_calendar import DayCalendar
from modern_gl.desktop.theme import P
from modern_gl.domain.period_input import parse_date
from modern_gl.i18n import tr

HINT = "5 · 5.10 · 051025 · вчера · +3"
ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def edited_date(edit: DateEdit) -> date:
    """The date in a date field (PySide types QDate.toPython() as object)."""
    return cast(date, edit.date().toPython())


class DateEdit(QLineEdit):
    """A date field with the calls of QDateEdit the forms use: date, setDate,
    setDateRange, dateChanged."""

    dateChanged = Signal(QDate)

    def __init__(self, value: QDate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._date = value
        self._first: QDate | None = None
        self._last: QDate | None = None
        self.setObjectName("date")
        self.setPlaceholderText(HINT)
        calendar = self.addAction(
            icons.icon("calendar", P.secondary), QLineEdit.ActionPosition.TrailingPosition
        )
        calendar.setToolTip(tr("Календарь"))
        calendar.triggered.connect(self.show_calendar)
        self.textEdited.connect(lambda _text: self._mark(False))
        self._show()

    def date(self) -> QDate:
        """The date; one typed and understood counts even before Enter (Ctrl+S)."""
        if self.isModified() and self._parsed() is not None:
            self._typed()
        return self._date

    def setDate(self, value: QDate) -> None:
        value = self._clamped(value)
        changed = value != self._date
        self._date = value
        self._show()
        if changed:
            self.dateChanged.emit(value)

    def setDateRange(self, first: QDate, last: QDate) -> None:
        self._first, self._last = first, last
        self.setDate(self._date)

    def show_calendar(self) -> None:
        if self.isReadOnly() or not self.isEnabled():
            return
        self._typed()
        window = CalendarWindow(
            cast(date, self._date.toPython()),
            *(None if d is None else cast(date, d.toPython()) for d in (self._first, self._last)),
            parent=self,
        )
        window.chosen.connect(lambda day: self.setDate(to_qdate(day)))
        window.open_under(self)
        self.calendar_shown = window  # tests reach the open calendar

    # ---- the keys --------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in ENTER_KEYS and self.isModified() and not self._typed():
            event.accept()  # not understood: said so, and the cursor stays here
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not self.isReadOnly():
            self._typed()
            self.setDate(self._date.addDays(-1 if key == Qt.Key.Key_Up else 1))
            return
        if key == Qt.Key.Key_Escape and self.isModified():
            self._show()  # what was typed is dropped
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        if event.reason() != Qt.FocusReason.MouseFocusReason:
            self.selectAll()  # typing replaces the date

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if self.isModified() and not self._typed():
            self._show()  # the field shows the date that stays
        super().focusOutEvent(event)

    def event(self, e: QEvent) -> bool:
        # Enter after a typed date is the field's, not a shortcut of the page
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and e.key() in ENTER_KEYS
            and self.isModified()
        ):
            e.accept()
            return True
        return super().event(e)

    # ---- the parts -------------------------------------------------------------------

    def _parsed(self) -> QDate | None:
        shown = cast(date, self._date.toPython())
        day = parse_date(self.text(), date.today(), shown)
        if day is None:
            return None
        value = to_qdate(day)
        return value if self._clamped(value) == value else None

    def _typed(self) -> bool:
        """What was typed becomes the date; False (and red) when it is not one."""
        if not self.isModified():
            return True
        value = self._parsed()
        if value is None:
            self._mark(True)
            return False
        self.setDate(value)
        self._show()  # the same date retyped: shown in full all the same
        return True

    def _clamped(self, value: QDate) -> QDate:
        if self._first is not None and value < self._first:
            return self._first
        if self._last is not None and value > self._last:
            return self._last
        return value

    def _show(self) -> None:
        self.setText(self._date.toString("dd.MM.yyyy"))
        self.setModified(False)
        self._mark(False)
        self.setToolTip(tr("Дата: {hint}", hint=HINT))

    def _mark(self, wrong: bool) -> None:
        if self.property("invalid") == wrong:
            return
        self.setProperty("invalid", wrong)
        self.style().unpolish(self)
        self.style().polish(self)


class CalendarWindow(QFrame):
    """The calendar of a date field: a click (or the keys and Enter) — that day; «Сегодня»."""

    chosen = Signal(object)  # a date

    def __init__(
        self, day: date, first: date | None, last: date | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("calendarWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        today = date.today()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(6)
        self.days = DayCalendar(day, today)
        self.days.set_span(day, day)
        self.days.set_limits(first, last)
        self.days.clicked.connect(self.choose)
        root.addWidget(self.days)
        line = QFrame()
        line.setObjectName("periodLine")
        line.setFixedHeight(1)
        root.addWidget(line)
        foot = QHBoxLayout()
        self.today_button = QPushButton(tr("Сегодня"))
        self.today_button.setObjectName("flat")
        self.today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.today_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.today_button.clicked.connect(lambda: self.choose(today))
        self.today_button.setEnabled(self.days.days.allowed(today))
        foot.addWidget(self.today_button)
        foot.addStretch(1)
        keys = QLabel(tr("← → ↑ ↓ — день"))
        keys.setObjectName("secondary")
        foot.addWidget(keys)
        root.addLayout(foot)

    def open_under(self, widget: QWidget) -> None:
        self.adjustSize()
        place = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        screen = QApplication.screenAt(place) or QApplication.primaryScreen()
        room = screen.availableGeometry()
        y = (
            place.y()
            if place.y() + self.height() <= room.bottom()
            else (widget.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4)
        )
        self.move(min(place.x(), room.right() - self.width()), y)
        self.show()
        self.days.days.setFocus()

    def choose(self, day: date) -> None:
        self.chosen.emit(day)
        self.close()


def date_edit(value: date, parent: QWidget | None = None) -> DateEdit:
    return DateEdit(to_qdate(value), parent)
