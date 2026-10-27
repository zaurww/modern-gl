"""The days of one month (D129): ‹ Октябрь 2026 ›, Пн … Вс, six weeks of days. The days
chosen are blue — one day, or a period drawn as a pale strip with blue ends; today is
outlined; the other months' days are pale. The same calendar picks the date of a form
(`date_field`) and the exact dates of a period (`period_window`); what a click means is
theirs — this only says which day."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from modern_gl.desktop import icons
from modern_gl.desktop.theme import P
from modern_gl.domain.dates import month_title
from modern_gl.i18n import N_, tr

WEEKDAYS = (N_("Пн"), N_("Вт"), N_("Ср"), N_("Чт"), N_("Пт"), N_("Сб"), N_("Вс"))
CELL_W, CELL_H, ROW_GAP, HEAD_H = 34, 32, 2, 24
RADIUS = 7
WEEKS = 6  # always six: the panel keeps its height from month to month


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(first: date, steps: int) -> date:
    n = first.year * 12 + first.month - 1 + steps
    return date(n // 12, n % 12 + 1, 1)


class Days(QWidget):
    """The painted grid: the weekdays and 6×7 days, the first Monday on or before the 1st."""

    clicked = Signal(object)  # a date
    hovered = Signal(object)  # a date, or None when the mouse left

    def __init__(self, month: date, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.month, self.today = month_start(month), today
        self.span: tuple[date, date] | None = None
        self.limits: tuple[date | None, date | None] = (None, None)
        self.hover: date | None = None
        self.keyed: date | None = None  # the day the keys stand on
        self.setMouseTracking(True)
        self.setFixedSize(self.sizeHint())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:
        return QSize(7 * CELL_W, HEAD_H + WEEKS * CELL_H + (WEEKS - 1) * ROW_GAP)

    def first_shown(self) -> date:
        return self.month - timedelta(days=self.month.weekday())

    def day_at(self, point: QPoint) -> date | None:
        row, col = (point.y() - HEAD_H) // (CELL_H + ROW_GAP), point.x() // CELL_W
        if point.y() < HEAD_H or not (0 <= row < WEEKS and 0 <= col < 7):
            return None
        day = self.first_shown() + timedelta(days=row * 7 + col)
        return day if self.allowed(day) else None

    def allowed(self, day: date) -> bool:
        first, last = self.limits
        return (first is None or day >= first) and (last is None or day <= last)

    def cell(self, day: date) -> QRectF:
        n = (day - self.first_shown()).days
        row, col = divmod(n, 7)
        return QRectF(col * CELL_W, HEAD_H + row * (CELL_H + ROW_GAP), CELL_W, CELL_H)

    # ---- the mouse and the keys --------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        day = self.day_at(event.position().toPoint())
        if day != self.hover:
            self.hover = day
            self.hovered.emit(day)
            self.update()

    def leaveEvent(self, event) -> None:
        self.hover = None
        self.hovered.emit(None)
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        day = self.day_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and day is not None:
            self.clicked.emit(day)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """← → a day, ↑ ↓ a week, PgUp PgDn a month; Enter takes the day."""
        key = Qt.Key(event.key())
        steps = {
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Up: -7,
            Qt.Key.Key_Down: 7,
        }
        start = self.keyed or (self.span[0] if self.span else self.today)
        if key in steps:
            self.move_keyed(start + timedelta(days=steps[key]))
        elif key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            month = add_months(month_start(start), -1 if key == Qt.Key.Key_PageUp else 1)
            self.move_keyed(month.replace(day=min(start.day, 28)))
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.allowed(start):
            self.clicked.emit(start)
        else:
            super().keyPressEvent(event)

    def move_keyed(self, day: date) -> None:
        if not self.allowed(day):
            return
        self.keyed = day
        if month_start(day) != self.month:
            parent = self.parentWidget()
            if isinstance(parent, DayCalendar):
                parent.show_month(day)
        self.update()

    # ---- the drawing -------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        self._paint_weekdays(p)
        self._paint_span(p)
        first = self.first_shown()
        for n in range(WEEKS * 7):
            self._paint_day(p, first + timedelta(days=n))
        p.end()

    def _paint_weekdays(self, p: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 0.9)
        p.setFont(font)
        p.setPen(QColor(P.header_text))
        for col, name in enumerate(WEEKDAYS):
            rect = QRectF(col * CELL_W, 0, CELL_W, HEAD_H)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, tr(name))
        p.setPen(Qt.PenStyle.NoPen)

    def _paint_span(self, p: QPainter) -> None:
        """A period: a pale strip, row by row, under its days."""
        if self.span is None or self.span[0] == self.span[1]:
            return
        first = self.first_shown()
        lo, hi = max(self.span[0], first), min(self.span[1], first + timedelta(WEEKS * 7 - 1))
        p.setBrush(QColor(P.accent_soft))
        while lo <= hi:
            row_end = min(hi, lo + timedelta(days=6 - lo.weekday()))
            p.drawRoundedRect(self.cell(lo).united(self.cell(row_end)), RADIUS, RADIUS)
            lo = row_end + timedelta(days=1)

    def _paint_day(self, p: QPainter, day: date) -> None:
        rect = self.cell(day)
        end = self.span is not None and day in self.span
        allowed = self.allowed(day)
        if end:
            p.setBrush(QColor(P.accent))
            p.drawRoundedRect(rect, RADIUS, RADIUS)
        elif allowed and day in (self.hover, self.keyed):
            p.setBrush(QColor(P.field_hover))
            p.drawRoundedRect(rect, RADIUS, RADIUS)
        if day == self.today and not end:
            p.setPen(QColor(P.accent))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if end or day == self.today else QFont.Weight.Normal)
        p.setFont(font)
        if end:
            color = P.on_accent
        elif day == self.today:
            color = P.accent
        elif not allowed or month_start(day) != self.month:
            color = P.tertiary
        else:
            color = P.text
        p.setPen(QColor(color))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(day.day))
        p.setPen(Qt.PenStyle.NoPen)


def nav_button(name: str, tooltip: str) -> QPushButton:
    """‹ or ›: a quiet icon (as `widgets.icon_button`, which imports the date field)."""
    b = QPushButton()
    b.setObjectName("more")
    b.setToolTip(tooltip)
    b.setIcon(icons.icon(name, P.secondary))
    b.setIconSize(QSize(18, 18))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


class DayCalendar(QWidget):
    """‹ the month › over its days; `clicked` — a day."""

    def __init__(self, month: date, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        head = QHBoxLayout()
        self.back = nav_button("previous", tr("Прошлый месяц  PgUp"))
        self.forward = nav_button("next", tr("Следующий месяц  PgDn"))
        self.back.clicked.connect(lambda: self.step(-1))
        self.forward.clicked.connect(lambda: self.step(1))
        self.title = QLabel()
        self.title.setObjectName("periodYear")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.back)
        head.addWidget(self.title, 1)
        head.addWidget(self.forward)
        column.addLayout(head)
        self.days = Days(month, today, self)
        column.addWidget(self.days)
        self.clicked, self.hovered = self.days.clicked, self.days.hovered
        self.show_month(month)

    def show_month(self, day: date) -> None:
        self.days.month = month_start(day)
        self.title.setText(month_title(f"{day:%Y-%m}"))
        self.days.update()

    def step(self, steps: int) -> None:
        self.show_month(add_months(self.days.month, steps))

    def set_span(self, first: date, last: date) -> None:
        """The days chosen: one (first == last) or a period."""
        self.days.span = (min(first, last), max(first, last))
        self.days.keyed = None
        self.days.update()

    def set_limits(self, first: date | None, last: date | None) -> None:
        self.days.limits = (first, last)
        self.days.update()
