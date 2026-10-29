"""The columns of the «Финансовая отчётность» page (D107): «Колонки ▾» by the period —
one period, by months, by quarters, against the period before or a year before; in the
profit and loss also by the elements of a directory (a shop, a project; D188) and a
share of the revenue after each figure; the titles of the columns and the figures under
them."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QPushButton

from modern_gl.desktop.preferences import STATEMENTS_COLUMNS, STATEMENTS_PERCENT, prefs
from modern_gl.desktop.reports_page.table import Column, figure
from modern_gl.desktop.widgets import MenuItem, button, menu_button, trailing_icon
from modern_gl.domain.dates import month_title
from modern_gl.domain.period_input import Period, describe, month_bounds, quarter_of
from modern_gl.i18n import N_, tr
from modern_gl.reporting.columns import (
    COMPARISONS,
    MONTHS,
    ONE,
    PREVIOUS,
    QUARTERS,
    SUBCONTO,
    YEAR_AGO,
    Amounts,
    column_periods,
    difference,
    percent,
    share,
)
from modern_gl.reporting.statements import Line

CHOICES = (
    (ONE, N_("Один период")),
    (MONTHS, N_("По месяцам")),
    (QUARTERS, N_("По кварталам")),
    None,
    (PREVIOUS, N_("С прошлым периодом")),
    (YEAR_AGO, N_("С прошлым годом")),
)
Directories = Callable[[], list[tuple[int, str]]]  # (kind id, name) of the profit and loss


class ColumnsChoice:
    """«Колонки ▾»: a quiet button with the choice in it, remembered between sessions.
    `directories()` — the directories a profit and loss can be split by, `profit()` —
    whether the page shows the profit and loss now (the split and the share are its)."""

    def __init__(self, on_change, directories: Directories, profit: Callable[[], bool]) -> None:
        remembered = prefs()
        self.mode, self.directory = ONE, ""  # the directory's name: the ids are per company
        saved = remembered.view(STATEMENTS_COLUMNS, ONE)
        if saved in dict(c for c in CHOICES if c):
            self.mode = saved
        elif saved.startswith(f"{SUBCONTO}:"):
            self.mode, self.directory = SUBCONTO, saved.split(":", 1)[1]
        self.percent = remembered.flag(STATEMENTS_PERCENT, False)
        self.on_change, self.directories, self.profit = on_change, directories, profit
        self.button: QPushButton = trailing_icon(button("", "segment"))
        menu_button(self.button, self._items)
        self._show()

    def choose(self, mode: str, directory: str = "") -> None:
        self.mode, self.directory = mode, directory
        prefs().set_view(STATEMENTS_COLUMNS, f"{mode}:{directory}" if directory else mode)
        self._show()
        self.on_change()

    def toggle_percent(self) -> None:
        self.percent = not self.percent
        prefs().set(STATEMENTS_PERCENT, self.percent)
        self.on_change()

    def effective(self) -> str:
        """The mode the page computes: the split only in the profit and loss and only
        when the company has the directory; otherwise one period."""
        if self.mode != SUBCONTO:
            return self.mode
        return SUBCONTO if self.profit() and self.kind_id() is not None else ONE

    def kind_id(self) -> int | None:
        return next((k for k, name in self.directories() if name == self.directory), None)

    def _items(self) -> list[MenuItem]:
        def mark(key: str, caption: str, on: bool | None = None) -> str:
            chosen = key == self.mode if on is None else on
            return ("✓  " if chosen else "     ") + caption

        items: list[MenuItem] = [
            (mark(c[0], tr(c[1])), lambda key=c[0]: self.choose(key)) if c is not None else None
            for c in CHOICES
        ]
        if not self.profit():
            return items
        directories = self.directories()
        if directories:
            items.append(None)
            items.extend(
                (
                    mark(SUBCONTO, tr("По субконто: {name}", name=name), on),
                    lambda name=name: self.choose(SUBCONTO, name),
                )
                for _, name in directories
                for on in [self.mode == SUBCONTO and self.directory == name]
            )
        items.append(None)
        items.append((mark("", tr("Процент от выручки"), self.percent), self.toggle_percent))
        return items

    def _show(self) -> None:
        if self.mode == SUBCONTO:
            caption = tr("По субконто: {name}", name=self.directory)
        else:
            caption = tr(dict(c for c in CHOICES if c)[self.mode])
        self.button.setText(tr("Колонки: {what}", what=caption) + "     ")


def periods_of(mode: str, period: Period, balance: bool) -> list[Period]:
    """What is computed: a balance has no «Итого» of months (it is the last month); a
    split is of the one period."""
    periods = column_periods(ONE if mode == SUBCONTO else mode, period)
    if balance and mode in (MONTHS, QUARTERS) and len(periods) > 1:
        periods = periods[:-1]
    return periods


def amount_columns(
    mode: str,
    periods: list[Period],
    balance: bool,
    split: Sequence[tuple[int | None, str]] = (),
    revenue: Amounts | None = None,
) -> list[Column]:
    """A column per period, or per element of the split and the whole; a comparison adds
    the difference and the percent; `revenue` (per column) adds the share of it after
    each figure."""
    if mode == SUBCONTO:
        titles = [name or tr("Не указано") for _, name in split] + [tr("Итого")]
    else:
        titles = _titles(mode, periods, balance)
    group = ""
    if balance and mode == MONTHS and len(periods) > 1:
        group = tr("На конец месяца")
    elif balance and mode == QUARTERS and len(periods) > 1:
        group = tr("На конец квартала")
    columns: list[Column] = []
    for i, title in enumerate(titles):
        columns.append(_figure_column(title, i, group, len(titles) > 1))
        if revenue is not None:
            columns.append(_share_column(i, revenue))
    if mode in COMPARISONS:
        columns.append(_column(tr("Разница"), difference))
        columns.append(_column("%", percent))
    return columns


def column_period(mode: str, periods: list[Period], column: Column | None) -> Period | None:
    """The period of a figure column; None: a difference, a percent, a share."""
    if column is None or not column.key.startswith("figure:"):
        return None
    index = int(column.key.split(":")[1])
    if mode == SUBCONTO:
        return periods[0]
    if 0 <= index < len(periods):
        return periods[index]
    return None


def column_element(column: Column | None, split: Sequence[tuple[int | None, str]]) -> int | None:
    """The element of the split a figure column is of (not the whole, not a share)."""
    if column is None or not column.key.startswith("figure:"):
        return None
    index = int(column.key.split(":")[1])
    return split[index][0] if index < len(split) else None


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
    name = month_title(f"{first:%Y-%m}")
    if not with_year:
        name = name.rsplit(" ", 1)[0]
    if period != month_bounds(first.year, first.month):
        name += f" {first.day}–{last.day}"  # a month cut by the period
    return name


def _figure_column(title: str, index: int, group: str, cell: bool) -> Column:
    column = _column(title, lambda amounts: amounts[index], group)
    column.cell = cell
    column.key = f"figure:{index}"
    return column


def _share_column(index: int, revenue: Amounts) -> Column:
    column = _column("%", lambda amounts: share(amounts[index], revenue[index]))
    column.key = f"share:{index}"
    return column


def _column(title: str, how, group: str = "") -> Column:
    """A heading has no figures at all: empty, not a dash."""

    def value(r: Line) -> int | None:
        return None if r.kind == "heading" else how(r.amount)

    def text(r: Line) -> str | None:
        return None if r.kind == "heading" else figure(value(r))

    return Column(title, text, right=True, value=value, group=group)
