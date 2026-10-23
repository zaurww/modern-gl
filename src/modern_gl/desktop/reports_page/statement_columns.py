"""The columns of the «Финансовая отчётность» page (D107): «Колонки ▾» by the period —
one period, by months, by quarters, against the period before or a year before; the
titles of the columns and the figures under them."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton

from modern_gl.desktop.reports_page.table import Column, figure
from modern_gl.desktop.widgets import MenuItem, button, menu_button, trailing_icon
from modern_gl.domain.dates import month_name
from modern_gl.domain.period_input import Period, describe, month_bounds, quarter_of
from modern_gl.i18n import tr
from modern_gl.reporting.columns import (
    COMPARISONS,
    MONTHS,
    ONE,
    PREVIOUS,
    QUARTERS,
    YEAR_AGO,
    column_periods,
    difference,
    percent,
)
from modern_gl.reporting.statements import Line

SETTING = "reports/statements_columns"
CHOICES = (
    (ONE, "Один период"),
    (MONTHS, "По месяцам"),
    (QUARTERS, "По кварталам"),
    None,
    (PREVIOUS, "С прошлым периодом"),
    (YEAR_AGO, "С прошлым годом"),
)


class ColumnsChoice:
    """«Колонки ▾»: a quiet button with the choice in it, remembered between sessions."""

    def __init__(self, on_change) -> None:
        self.mode = str(QSettings().value(SETTING, ONE))
        if self.mode not in dict(c for c in CHOICES if c):
            self.mode = ONE
        self.on_change = on_change
        self.button: QPushButton = trailing_icon(button("", "segment"))
        menu_button(self.button, self._items)
        self._show()

    def choose(self, mode: str) -> None:
        self.mode = mode
        QSettings().setValue(SETTING, mode)
        self._show()
        self.on_change()

    def _items(self) -> list[MenuItem]:
        def mark(key: str, caption: str) -> str:
            return ("✓  " if key == self.mode else "     ") + tr(caption)

        return [
            (mark(*c), lambda key=c[0]: self.choose(key)) if c is not None else None
            for c in CHOICES
        ]

    def _show(self) -> None:
        caption = dict(c for c in CHOICES if c)[self.mode]
        self.button.setText(tr("Колонки: {what}", what=tr(caption)) + "     ")


def periods_of(mode: str, period: Period, balance: bool) -> list[Period]:
    """What is computed: a balance has no «Итого» of months (it is the last month)."""
    periods = column_periods(mode, period)
    if balance and mode in (MONTHS, QUARTERS) and len(periods) > 1:
        periods = periods[:-1]
    return periods


def amount_columns(mode: str, periods: list[Period], balance: bool) -> list[Column]:
    """A column per period; a comparison adds the difference and the percent."""
    titles = _titles(mode, periods, balance)
    group = ""
    if balance and mode == MONTHS and len(periods) > 1:
        group = tr("На конец месяца")
    elif balance and mode == QUARTERS and len(periods) > 1:
        group = tr("На конец квартала")
    columns = [_figure_column(title, i, group, len(titles) > 1) for i, title in enumerate(titles)]
    if mode in COMPARISONS:
        columns.append(_column(tr("Разница"), difference))
        columns.append(_column("%", percent))
    return columns


def column_period(mode: str, periods: list[Period], column: int) -> Period | None:
    """The period of a figure column (1 is the first after the names); None: a difference,
    a percent."""
    index = column - 1
    if 0 <= index < len(periods):
        return periods[index]
    return None


# ---- the parts ---------------------------------------------------------------------------


def _titles(mode: str, periods: list[Period], balance: bool) -> list[str]:
    if len(periods) == 1:
        if balance:
            return [tr("На {day}", day=f"{periods[0][1]:%d.%m.%Y}")]
        return [tr("За период")]
    if mode in COMPARISONS:
        if balance:
            return [f"{last:%d.%m.%Y}" for _, last in periods]
        return [describe(p) for p in periods]
    years = {p[0].year for p in periods}
    parts = periods if balance else periods[:-1]  # the last of flows is the whole
    titles = [_part_title(mode, p, len(years) > 1) for p in parts]
    return titles if balance else [*titles, tr("Итого")]


def _part_title(mode: str, period: Period, with_year: bool) -> str:
    first, last = period
    if mode == QUARTERS:
        n = quarter_of(first)
        return (
            tr("{n} квартал {year}", n=n, year=first.year) if with_year else tr("{n} квартал", n=n)
        )
    name = month_name(f"{first:%Y-%m}")
    name = name[:1].upper() + name[1:]
    if not with_year:
        name = name.rsplit(" ", 1)[0]
    if period != month_bounds(first.year, first.month):
        name += f" {first.day}–{last.day}"  # a month cut by the period
    return name


def _figure_column(title: str, index: int, group: str, cell: bool) -> Column:
    column = _column(title, lambda amounts: amounts[index], group)
    column.cell = cell
    return column


def _column(title: str, how, group: str = "") -> Column:
    """A heading has no figures at all: empty, not a dash."""

    def value(r: Line) -> int | None:
        return None if r.kind == "heading" else how(r.amount)

    def text(r: Line) -> str | None:
        return None if r.kind == "heading" else figure(value(r))

    return Column(title, text, right=True, value=value, group=group)
