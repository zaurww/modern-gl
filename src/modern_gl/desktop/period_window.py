"""The period chosen with the mouse (D105, D129): the calendar icon of the period field
opens this panel — the usual periods on the left (one click), the year with its months
and quarters in the middle (a click: that month; Shift+click: from the period's start to
that month, as in 1C), the days of a month on the right (a click — the start, a second
click — the end), the exact dates below. What is chosen now is blue; typing in the field
stays the quick way, this is the one that shows everything."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.date_field import DateEdit, edited_date, to_qdate
from modern_gl.desktop.day_calendar import DayCalendar
from modern_gl.desktop.widgets import button, icon_button
from modern_gl.domain.dates import month_short
from modern_gl.domain.period_input import (
    Period,
    month_bounds,
    parse_period,
    quarter_bounds,
)
from modern_gl.domain.periods import DAY, LAST_MONTH, LAST_WEEK, MONTH, WEEK, span_period
from modern_gl.i18n import tr

# the usual periods: what is typed for them (so the field and the panel agree), caption
PRESETS = (
    ("м", "Этот месяц"),
    ("пм", "Прошлый месяц"),
    ("кв", "Этот квартал"),
    ("пк", "Прошлый квартал"),
    ("сг", "С начала года"),
    ("г", "Этот год"),
    ("пг", "Прошлый год"),
)
# the portal's (D53): its pages look at days and weeks, not at quarters and years
PORTAL_PRESETS = (
    (DAY, "Вчера"),
    (WEEK, "Эта неделя"),
    (LAST_WEEK, "Прошлая неделя"),
    (MONTH, "Этот месяц"),
    (LAST_MONTH, "Прошлый месяц"),
)

Preset = tuple[str, str, Period]  # a key, the caption (to translate), the period


def report_presets(today: date) -> list[Preset]:
    return [
        (typed, caption, period)
        for typed, caption in PRESETS
        if (period := parse_period(typed, today)) is not None
    ]


def portal_presets(today: date) -> list[Preset]:
    return [(span, caption, span_period(span, today)) for span, caption in PORTAL_PRESETS]


class PeriodWindow(QFrame):
    chosen = Signal(object)  # a Period

    def __init__(
        self,
        period: Period,
        today: date,
        parent: QWidget | None = None,
        presets: list[Preset] | None = None,
        dates: Period | None = None,  # the dates the field shows, when it ends `period` early
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("periodWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.period, self.today = period, today
        self.presets = report_presets(today) if presets is None else presets
        self.dates = dates or period
        self.year = period[1].year
        self.anchor: date | None = None  # the first click on a day, before the second
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(16)
        top = QHBoxLayout()
        top.setSpacing(24)
        top.addLayout(self._presets())
        top.addWidget(self._line())
        top.addLayout(self._calendar())
        top.addWidget(self._line())
        top.addWidget(self._days())
        root.addLayout(top)
        root.addWidget(self._line(horizontal=True))
        root.addLayout(self._dates())
        self._show_year()

    def open_under(self, widget: QWidget) -> None:
        self.adjustSize()
        place = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        screen = QApplication.screenAt(place) or QApplication.primaryScreen()
        room = screen.availableGeometry()
        self.move(min(place.x(), room.right() - self.width()), place.y())
        self.show()
        self.first.setFocus()

    def choose(self, period: Period) -> None:
        self.chosen.emit(period)
        self.close()

    def choose_month(self, month: int, extend: bool = False) -> None:
        """A month of the year shown; `extend` (Shift): from the period's start to it —
        or from it to the period's end, when it is before."""
        first, last = month_bounds(self.year, month)
        if extend:
            first, last = min(first, self.period[0]), max(last, self.period[1])
        self.choose((first, last))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._take_dates()
            return
        super().keyPressEvent(event)

    # ---- the parts ---------------------------------------------------------------------

    def _presets(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(2)
        self.preset_buttons: dict[str, QPushButton] = {}
        for key, caption, period in self.presets:
            b = self._cell(tr(caption), "periodPreset")
            b.setChecked(period == self.period)
            b.clicked.connect(lambda _=False, p=period: self.choose(p))
            column.addWidget(b)
            self.preset_buttons[key] = b
        column.addStretch(1)
        return column

    def _calendar(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        head = QHBoxLayout()
        back = icon_button("previous", tr("Прошлый год"))
        forward = icon_button("next", tr("Следующий год"))
        back.clicked.connect(lambda: self._step_year(-1))
        forward.clicked.connect(lambda: self._step_year(1))
        self.year_label = QLabel()
        self.year_label.setObjectName("periodYear")
        self.year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(back)
        head.addWidget(self.year_label, 1)
        head.addWidget(forward)
        column.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self.month_buttons: list[QPushButton] = []
        for month in range(1, 13):
            b = self._cell(month_short(month), "periodCell")
            b.setToolTip(tr("Shift+щелчок — от начала периода до этого месяца"))
            b.clicked.connect(lambda _=False, m=month: self._month_clicked(m))
            grid.addWidget(b, (month - 1) // 3, (month - 1) % 3)
            self.month_buttons.append(b)
        self.quarter_buttons: list[QPushButton] = []
        for quarter in range(1, 5):
            b = self._cell(tr("{n} кв", n=quarter), "periodCell")
            b.clicked.connect(lambda _=False, q=quarter: self.choose(quarter_bounds(self.year, q)))
            grid.addWidget(b, quarter - 1, 4)
            self.quarter_buttons.append(b)
        grid.setColumnMinimumWidth(3, 12)  # air between the months and the quarters
        self.year_button = self._cell(tr("Весь год"), "periodCell")
        self.year_button.clicked.connect(
            lambda: self.choose((date(self.year, 1, 1), date(self.year, 12, 31)))
        )
        grid.addWidget(self.year_button, 4, 0, 1, 5)
        column.addLayout(grid)
        column.addStretch(1)  # the year stands level with the month of days beside it
        return column

    def _dates(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.first, self.last = (
            DateEdit(to_qdate(self.dates[0])),
            DateEdit(to_qdate(self.dates[1])),
        )
        for caption, field in ((tr("С"), self.first), (tr("по"), self.last)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            field.setFixedWidth(140)
            field.dateChanged.connect(lambda _d: self._show_typed())
            row.addWidget(label)
            row.addWidget(field)
        row.addStretch(1)
        done = button(tr("Готово"), "primary")
        done.clicked.connect(self._take_dates)
        row.addWidget(done)
        return row

    def _days(self) -> DayCalendar:
        self.days = DayCalendar(self.dates[0], self.today)
        self.days.set_span(*self.dates)
        self.days.clicked.connect(self.day_clicked)
        self.days.hovered.connect(self._day_hovered)
        return self.days

    def day_clicked(self, day: date) -> None:
        """The first click — the start, the second — the end (either way round); the dates
        below follow, «Готово» or Enter takes them."""
        first, last = (day, day) if self.anchor is None else sorted((self.anchor, day))
        self.anchor = day if self.anchor is None else None
        self._fill(first, last)

    def _day_hovered(self, day: date | None) -> None:
        if self.anchor is not None:  # the period to be, under the mouse
            self.days.set_span(self.anchor, day or self.anchor)

    def _fill(self, first: date, last: date) -> None:
        for field, day in ((self.first, first), (self.last, last)):
            field.blockSignals(True)
            field.setDate(to_qdate(day))
            field.blockSignals(False)
        self.days.set_span(first, last)

    def _show_typed(self) -> None:
        """A date typed below: the calendar shows it."""
        self.anchor = None
        first = edited_date(self.first)
        self.days.set_span(first, edited_date(self.last))
        self.days.show_month(first)

    @staticmethod
    def _line(horizontal: bool = False) -> QFrame:
        line = QFrame()
        line.setObjectName("periodLine")
        if horizontal:
            line.setFixedHeight(1)
        else:
            line.setFixedWidth(1)
        return line

    @staticmethod
    def _cell(text: str, kind: str) -> QPushButton:
        b = button(text, kind)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Tab walks the two dates only
        return b

    def _month_clicked(self, month: int) -> None:
        shift = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        self.choose_month(month, bool(shift))

    def _step_year(self, steps: int) -> None:
        self.year += steps
        self._show_year()

    def _show_year(self) -> None:
        """The year's months and quarters inside the period are blue."""
        self.year_label.setText(str(self.year))
        first, last = self.period
        for month, b in enumerate(self.month_buttons, 1):
            a, z = month_bounds(self.year, month)
            b.setChecked(first <= a and z <= last)
        for quarter, b in enumerate(self.quarter_buttons, 1):
            b.setChecked(self.period == quarter_bounds(self.year, quarter))
        self.year_button.setChecked(self.period == (date(self.year, 1, 1), date(self.year, 12, 31)))

    def _take_dates(self) -> None:
        first, last = edited_date(self.first), edited_date(self.last)
        self.choose((first, last) if first <= last else (last, first))
