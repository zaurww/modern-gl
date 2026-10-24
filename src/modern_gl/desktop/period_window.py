"""The period chosen with the mouse (D105): ▾ by the period field opens this panel — the
usual periods on the left (one click), the year with its months and quarters on the
right (a click: that month; Shift+click: from the period's start to that month, as in
1C), the exact dates below. What is chosen now is blue; typing in the field stays the
quick way, this is the one that shows everything."""

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
from modern_gl.desktop.widgets import button, icon_button
from modern_gl.domain.dates import month_title
from modern_gl.domain.period_input import (
    Period,
    month_bounds,
    parse_period,
    quarter_bounds,
)
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


class PeriodWindow(QFrame):
    chosen = Signal(object)  # a Period

    def __init__(self, period: Period, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("periodWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.period, self.today = period, today
        self.year = period[1].year
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(24)
        top.addLayout(self._presets())
        top.addLayout(self._calendar())
        root.addLayout(top)
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
        for typed, caption in PRESETS:
            period = parse_period(typed, self.today)
            if period is None:
                continue
            b = self._cell(tr(caption), "periodPreset")
            b.setChecked(period == self.period)
            b.clicked.connect(lambda _=False, p=period: self.choose(p))
            column.addWidget(b)
            self.preset_buttons[typed] = b
        column.addStretch(1)
        return column

    def _calendar(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(8)
        head = QHBoxLayout()
        back = icon_button("back", tr("Прошлый год"))
        forward = icon_button("forward", tr("Следующий год"))
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
            name = month_title(f"2000-{month:02d}").split()[0]
            b = self._cell(name, "periodCell")
            b.setToolTip(tr("Shift+щелчок — от начала периода до этого месяца"))
            b.clicked.connect(lambda _=False, m=month: self._month_clicked(m))
            grid.addWidget(b, (month - 1) // 3, (month - 1) % 3)
            self.month_buttons.append(b)
        self.quarter_buttons: list[QPushButton] = []
        for quarter in range(1, 5):
            b = self._cell(tr("{n} квартал", n=quarter), "periodCell")
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
        return column

    def _dates(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.first, self.last = (
            DateEdit(to_qdate(self.period[0])),
            DateEdit(to_qdate(self.period[1])),
        )
        for caption, field in ((tr("С"), self.first), (tr("по"), self.last)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            field.setFixedWidth(140)
            row.addWidget(label)
            row.addWidget(field)
        row.addStretch(1)
        done = button(tr("Готово"), "primary")
        done.clicked.connect(self._take_dates)
        row.addWidget(done)
        return row

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
