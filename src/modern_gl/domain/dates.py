from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from modern_gl.i18n import tr, upper


def iso_date(value: date | str) -> str:
    """Normalize a date or 'YYYY-MM-DD' string; rejects datetimes and garbage."""
    if isinstance(value, datetime):
        raise TypeError("expected a date, got a datetime")
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def ru_date(iso: str) -> str:
    """'2026-03-05' -> '05.03.2026', as dates are shown to the user."""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def next_day(day: date | str) -> str:
    """The day after (ISO): «2026-12-31» -> «2027-01-01»."""
    return (date.fromisoformat(iso_date(day)) + timedelta(days=1)).isoformat()


def date_range(first: date | str, last: date | str, sep: str = " — ") -> str:
    """'01.10 — 15.10.2026'; across a new year both years: '29.12.2025 — 04.01.2026';
    a single day: '20.10.2026'."""
    start, end = ru_date(iso_date(first)), ru_date(iso_date(last))
    if start == end:
        return end
    return f"{start[:5] if start[-4:] == end[-4:] else start}{sep}{end}"


_MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


_SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_short(month: int) -> str:
    """3 -> 'Mar': a month in three English letters, the same in every language (D129)."""
    return _SHORT_MONTHS[month - 1]


def month_name(month: str) -> str:
    """'2026-03' -> 'март 2026' (in the interface's language)."""
    return f"{tr(_MONTHS[int(month[5:7]) - 1])} {month[:4]}"


def month_title(month: str) -> str:
    """'2026-06' -> 'Июнь 2026' / 'İyun 2026': a month as a heading."""
    name = month_name(month)
    return upper(name[:1]) + name[1:]


def month_days(year: int, month: int) -> tuple[date, date]:
    """The first and the last day of a month — the one place they are counted."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_end(value: date | str) -> str:
    """The last day of the month of `value`: '2026-09-14' -> '2026-09-30'."""
    day = date.fromisoformat(iso_date(value))
    return month_days(day.year, day.month)[1].isoformat()


def earlier_months(value: date | str, count: int = 12) -> list[str]:
    """The last days of the `count` months before the month of `value`, latest first:
    the months a purchase's expense may belong to (D65)."""
    first = date.fromisoformat(iso_date(value)).replace(day=1)
    result = []
    for _ in range(count):
        last = date.fromordinal(first.toordinal() - 1)
        result.append(last.isoformat())
        first = last.replace(day=1)
    return result
