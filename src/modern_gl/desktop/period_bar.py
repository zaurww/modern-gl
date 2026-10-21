"""The period of a portal window at a click: «Вчера · Эта неделя · Прошлая неделя · Этот
месяц · Прошлый месяц · Произвольный». A quick period shows its dates as text; the
dates to type or pick from a calendar appear only for «Произвольный»."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from modern_gl.desktop.widgets import button, date_edit, edited_date, to_qdate
from modern_gl.domain.dates import ru_date
from modern_gl.domain.periods import DAY, LAST_MONTH, LAST_WEEK, MONTH, WEEK, quick_period
from modern_gl.i18n import tr

CUSTOM = "custom"
CAPTIONS = (
    (DAY, "Вчера"),
    (WEEK, "Эта неделя"),
    (LAST_WEEK, "Прошлая неделя"),
    (MONTH, "Этот месяц"),
    (LAST_MONTH, "Прошлый месяц"),
    (CUSTOM, "Произвольный"),
)


class PeriodBar(QWidget):
    changed = Signal()

    def __init__(
        self,
        today: date,
        span: str = MONTH,
        through_today: bool = False,  # «this week / month» up to today, not yesterday
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.today = today
        self.through_today = through_today
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.spans = QButtonGroup(self)
        self.span_buttons: dict[str, QPushButton] = {}
        for key, caption in CAPTIONS:
            choice = button(tr(caption), "segment")
            choice.setCheckable(True)
            bold = QFont(choice.font())
            bold.setBold(True)  # checked is bold: the width must not jump or clip
            choice.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(choice.text()) + 36)
            choice.clicked.connect(lambda _checked=False, key=key: self.choose(key))
            self.spans.addButton(choice)
            self.span_buttons[key] = choice
            row.addWidget(choice)
        row.addSpacing(10)
        self.dates = QLabel()  # «13.10–19.10.2026» of a quick period
        self.dates.setObjectName("secondary")
        row.addWidget(self.dates)
        first, last = quick_period(MONTH, today, through_today)
        self.date_from = date_edit(first)
        self.date_to = date_edit(last)
        self.dash = QLabel("—")
        self.dash.setObjectName("secondary")
        for widget in (self.date_from, self.dash, self.date_to):
            if widget is not self.dash:
                widget.setFixedWidth(130)
            row.addWidget(widget)
        for edit in (self.date_from, self.date_to):
            edit.dateChanged.connect(self.changed)
        self.choose(span)

    def span(self) -> str:
        return next(key for key, choice in self.span_buttons.items() if choice.isChecked())

    def period(self) -> tuple[date, date]:
        return edited_date(self.date_from), edited_date(self.date_to)

    def choose(self, span: str) -> None:
        if span != CUSTOM:
            self._set_dates(*quick_period(span, self.today, self.through_today))
        self.span_buttons[span].setChecked(True)
        custom = span == CUSTOM
        for widget in (self.date_from, self.dash, self.date_to):
            widget.setVisible(custom)
        self.dates.setVisible(not custom)
        self.dates.setText(period_dates(*self.period()))
        if custom and self.isVisible():
            self.date_from.setFocus()
        self.changed.emit()

    def set_period(self, first: date, last: date) -> None:
        """Dates from elsewhere (the same period in another window): the quick period
        they are, else «Произвольный»."""
        span = next(
            (
                key
                for key, _caption in CAPTIONS[:-1]
                if quick_period(key, self.today, self.through_today) == (first, last)
            ),
            CUSTOM,
        )
        self._set_dates(first, last)
        self.choose(span)

    def _set_dates(self, first: date, last: date) -> None:
        for edit, day in ((self.date_from, first), (self.date_to, last)):
            edit.blockSignals(True)
            edit.setDate(to_qdate(day))
            edit.blockSignals(False)


def period_dates(first: date, last: date) -> str:
    """'20.10.2026', '13.10–19.10.2026', '29.12.2025–04.01.2026'."""
    end = ru_date(last.isoformat())
    if first == last:
        return end
    start = ru_date(first.isoformat())
    return f"{start[:5] if first.year == last.year else start}–{end}"
