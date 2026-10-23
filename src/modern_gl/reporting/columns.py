"""The columns of a financial statement (D107): one period; its months or quarters side by
side with the whole period; the period against the one before or a year before.

A statement is built once for all its columns: an amount of a line is `Amounts`, one
figure per column, and the builders add and subtract them as numbers — a line is shown
when any column has a figure. The «Итого» of months is one more column computed the same
way (the whole period), so it is never a sum that could differ from the report itself:
the cash flow's money at the start and the end are not sums of months.

The difference and the percent of a comparison are figures too: the percent in hundredths
(1234 = 12.34 %), so it is shown and exported like money; None when there is no base."""

from __future__ import annotations

from datetime import date

from modern_gl.domain.period_input import Period, month_bounds, quarter_bounds, quarter_of, shift

ONE, MONTHS, QUARTERS, PREVIOUS, YEAR_AGO = "one", "months", "quarters", "previous", "year_ago"
COMPARISONS = (PREVIOUS, YEAR_AGO)
MAX_COLUMNS = 13  # months of more than a year are shown by quarters


class Amounts(tuple[int, ...]):
    """Figures of a line, one per column; empty is zero in every column."""

    @classmethod
    def at(cls, index: int, count: int, value: int) -> Amounts:
        return cls(value if i == index else 0 for i in range(count))

    def _pair(self, other: object) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
        if isinstance(other, int):
            other = (other,) * len(self) if other else ()
        if not isinstance(other, tuple):
            return None
        n = max(len(self), len(other))
        return tuple(self) + (0,) * (n - len(self)), tuple(other) + (0,) * (n - len(other))

    def __add__(self, other: object) -> Amounts:  # type: ignore[override]
        pair = self._pair(other)
        if pair is None:
            return NotImplemented
        return Amounts(a + b for a, b in zip(*pair, strict=True))

    __radd__ = __add__

    def __sub__(self, other: object) -> Amounts:
        pair = self._pair(other)
        if pair is None:
            return NotImplemented
        return Amounts(a - b for a, b in zip(*pair, strict=True))

    def __rsub__(self, other: object) -> Amounts:
        return -(self - other)

    def __neg__(self) -> Amounts:
        return Amounts(-a for a in self)

    def __mul__(self, sign: object) -> Amounts:  # type: ignore[override]
        if not isinstance(sign, int):
            return NotImplemented
        return Amounts(sign * a for a in self)

    __rmul__ = __mul__

    def __bool__(self) -> bool:
        return any(self)

    def __eq__(self, other: object) -> bool:
        pair = self._pair(other)
        return pair is not None and pair[0] == pair[1]

    __hash__ = tuple.__hash__

    def __getitem__(self, index):  # type: ignore[override]
        """A column past the end is zero, as the figures are."""
        if isinstance(index, int) and index >= len(self):
            return 0
        return super().__getitem__(index)


def total(amounts) -> Amounts:
    """The sum of figures (sum() of nothing is 0, not Amounts)."""
    result = Amounts()
    for a in amounts:
        result = result + a
    return result


def column_periods(mode: str, period: Period) -> list[Period]:
    """The periods the statement is computed for: the period itself; its months or
    quarters (cut to the period) and the whole period last; or the period and the one it
    is compared with."""
    first, last = period
    if mode == PREVIOUS:
        return [period, shift(period, -1)]
    if mode == YEAR_AGO:
        return [period, (year_before(first), year_before(last, _month_end(last)))]
    if mode == MONTHS and _count_months(period) > MAX_COLUMNS:
        mode = QUARTERS
    if mode == MONTHS:
        parts = [month_bounds(y, m) for y, m in _months(period)]
    elif mode == QUARTERS:
        quarters = dict.fromkeys((y, quarter_of(date(y, m, 1))) for y, m in _months(period))
        parts = [quarter_bounds(y, q) for y, q in quarters]
    else:
        return [period]
    cut = [(max(a, first), min(b, last)) for a, b in parts]
    return [*cut, period] if len(cut) > 1 else [period]


def year_before(day: date, month_end: bool = False) -> date:
    """The same day a year before; the end of a month stays the end (29.02 → 28.02)."""
    last = month_bounds(day.year - 1, day.month)[1]
    return last if month_end or day.day > last.day else day.replace(year=day.year - 1)


def difference(amounts: Amounts) -> int:
    """A comparison: the period less the one it is compared with."""
    return amounts[0] - amounts[1]


def percent(amounts: Amounts) -> int | None:
    """The change against the base in hundredths of a percent, rounded half away from
    zero; None without a base."""
    base = abs(amounts[1])
    if not base:
        return None
    change = difference(amounts) * 10_000
    return (abs(change) + base // 2) // base * (1 if change >= 0 else -1)


def _month_end(day: date) -> bool:
    return day == month_bounds(day.year, day.month)[1]


def _count_months(period: Period) -> int:
    first, last = period
    return (last.year - first.year) * 12 + last.month - first.month + 1


def _months(period: Period) -> list[tuple[int, int]]:
    first = period[0]
    start = first.year * 12 + first.month - 1
    return [((start + i) // 12, (start + i) % 12 + 1) for i in range(_count_months(period))]
