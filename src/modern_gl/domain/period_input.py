"""Periods and dates typed short, as in Todoist (D105): one field, a few letters, in
Russian, Azerbaijani (with or without the Azerbaijani letters) or English — all of them,
whatever the language of the interface.

A period:
  «пм» / «ka» — the last month, «м» / «ay» — this one, «кв» / «rüb» — this quarter,
  «пк» / «kr» — the last quarter, «г» / «il» — this year, «пг» / «ki» — the last year,
  «сг» / «ilb» — from the start of the year to today, «ск» / «rb» — of the quarter,
  «см» / «ab» — of the month; «окт», «okt 25», «10», «10.25», «10.2025» — a month (the
  latest one that is not ahead: «дек» in October is last December); «кв3», «3кв», «q3»,
  «r3 2025» — a quarter; «2025» — a year; «1.10-15.10», «1.10 — 15.10.25» — from … to;
  «15.10», «вчера» — a day.
A date:
  «5» — the 5th of the month shown, «5.10», «5.10.25», «051025», «05102025»; «сегодня» /
  «bu gün», «вчера» / «dünən», «завтра» / «sabah», «+3», «-1» — days from today.
Whatever is not understood is None: the field shows it is not, and keeps what it had."""

from __future__ import annotations

import re
from datetime import date, timedelta

from modern_gl.domain.dates import date_range, month_days, month_name
from modern_gl.i18n import fold, tr

Period = tuple[date, date]

# folded: «keçən» == «kecen», «rüb» == «rub»
TODAY_WORDS = ("сегодня", "сег", "bu gun", "bugun", "today")
YESTERDAY_WORDS = ("вчера", "dunen", "yesterday")
TOMORROW_WORDS = ("завтра", "sabah", "tomorrow")
MONTH_STEMS = (
    ("янв", "yan", "jan"),
    ("фев", "fev", "feb"),
    ("мар", "mar"),
    ("апр", "apr"),
    ("май", "мая", "may"),
    ("июн", "iyn", "iyun", "jun"),
    ("июл", "iyl", "iyul", "jul"),
    ("авг", "avq", "aug"),
    ("сен", "sen", "sep"),
    ("окт", "okt", "oct"),
    ("ноя", "noy", "nov"),
    ("дек", "dek", "dec"),
)
QUARTER_WORDS = ("кв", "квартал", "q", "r", "rub")


def month_bounds(year: int, month: int) -> Period:
    return month_days(year, month)


def quarter_bounds(year: int, quarter: int) -> Period:
    return month_bounds(year, 3 * quarter - 2)[0], month_bounds(year, 3 * quarter)[1]


def quarter_of(day: date) -> int:
    return (day.month - 1) // 3 + 1


def _presets(today: date) -> dict[str, Period]:
    last_month = today.replace(day=1) - timedelta(days=1)
    quarter = quarter_of(today)
    last_quarter = (today.year, quarter - 1) if quarter > 1 else (today.year - 1, 4)
    quarter_start = quarter_bounds(today.year, quarter)[0]
    periods = {
        ("м", "мес", "месяц", "этот месяц", "ay", "bu ay", "this month"): month_bounds(
            today.year, today.month
        ),
        ("пм", "прошлый месяц", "ka", "kecen ay", "lm", "last month"): month_bounds(
            last_month.year, last_month.month
        ),
        ("кв", "квартал", "этот квартал", "rub", "bu rub", "this quarter"): quarter_bounds(
            today.year, quarter
        ),
        ("пк", "прошлый квартал", "kr", "kecen rub", "lq", "last quarter"): quarter_bounds(
            *last_quarter
        ),
        ("г", "год", "этот год", "il", "bu il", "this year"): (
            date(today.year, 1, 1),
            date(today.year, 12, 31),
        ),
        ("пг", "прошлый год", "ki", "kecen il", "ly", "last year"): (
            date(today.year - 1, 1, 1),
            date(today.year - 1, 12, 31),
        ),
        ("сг", "с начала года", "ilb", "ilin evvelinden", "ytd"): (date(today.year, 1, 1), today),
        ("ск", "с начала квартала", "rb", "rubun evvelinden", "qtd"): (quarter_start, today),
        ("см", "с начала месяца", "ab", "ayin evvelinden", "mtd"): (today.replace(day=1), today),
    }
    return {word: period for words, period in periods.items() for word in words}


def parse_period(text: str, today: date) -> Period | None:
    """A period from what was typed; None when it is not one."""
    t = _clean(text)
    if not t:
        return None
    if (preset := _presets(today).get(t)) is not None:
        return preset
    for sep in ("..", "—", "–", "-"):
        if sep in t and not t.startswith(sep):
            left, right = (s.strip() for s in t.split(sep, 1))
            return _range(left, right, today)
    return _month(t, today) or _quarter(t, today) or _year(t) or _day_period(t, today)


def parse_date(text: str, today: date, shown: date | None = None) -> date | None:
    """A day from what was typed; a bare day number is in the month of `shown` (the
    date the field shows), else of today."""
    t = _clean(text)
    if not t:
        return None
    if t in TODAY_WORDS:
        return today
    if t in YESTERDAY_WORDS:
        return today - timedelta(days=1)
    if t in TOMORROW_WORDS:
        return today + timedelta(days=1)
    if m := re.fullmatch(r"([+-])\s*(\d{1,3})", t):
        days = int(m.group(2))
        return today + timedelta(days=days if m.group(1) == "+" else -days)
    return _numeric_date(t, shown or today)


def describe(period: Period) -> str:
    """How the field shows a period: «Октябрь 2026», «3 квартал 2026», «2026»,
    «05.10.2026», «01.10 — 15.10.2026», «29.12.2025 — 04.01.2026»."""
    first, last = period
    if _months_long(period) == 1:
        name = month_name(f"{first:%Y-%m}")
        return name[:1].upper() + name[1:]
    if first.year == last.year and (first, last) == quarter_bounds(first.year, quarter_of(first)):
        return tr("{n} квартал {year}", n=quarter_of(first), year=first.year)
    if (first, last) == (date(first.year, 1, 1), date(first.year, 12, 31)):
        return str(first.year)
    return date_range(first, last)


def shift(period: Period, steps: int) -> Period:
    """‹ ›: the same kind of period before or after — a month by a month, a quarter by a
    quarter, a year by a year; any other by its own length in days."""
    first, last = period
    months = _months_long(period)
    if months:
        start = first.year * 12 + first.month - 1 + steps * months
        end = start + months - 1
        return month_bounds(start // 12, start % 12 + 1)[0], month_bounds(end // 12, end % 12 + 1)[
            1
        ]
    days = (last - first).days + 1
    return first + timedelta(days=steps * days), last + timedelta(days=steps * days)


def _months_long(period: Period) -> int:
    """How many whole calendar months the period is (0: not whole months)."""
    first, last = period
    if first.day != 1 or last != month_bounds(last.year, last.month)[1]:
        return 0
    return (last.year - first.year) * 12 + last.month - first.month + 1


# ---- the parts ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    return " ".join(fold(text or "").split())


def _numeric_date(t: str, base: date) -> date | None:
    whole = re.fullmatch(r"\d{6}|\d{8}", t)  # 051025, 05102025
    parts = [t[:2], t[2:4], t[4:]] if whole else re.split(r"[./, ]+", t)
    if not 1 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    day = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else base.month
    year = _full_year(parts[2]) if len(parts) > 2 else base.year
    try:
        return date(year, month, day)
    except (ValueError, OverflowError):  # 31.02; a number too long for a date
        return None


def _full_year(text: str) -> int:
    return 2000 + int(text) if len(text) <= 2 else int(text)


def _range(left: str, right: str, today: date) -> Period | None:
    """«1.10-15.10.25»: the end's year (and month) are the start's when it lacks them."""
    end = _numeric_date(right, today)
    if end is None:
        return None
    start = _numeric_date(left, end)
    if start is None or start > end:
        return None
    return start, end


def _month(t: str, today: date) -> Period | None:
    """«окт», «okt 25», «октябрь 2025»; «10», «10.25», «10.2025»."""
    m = re.fullmatch(r"([a-zа-я]+)\.?\s*(\d{2}|\d{4})?", t)
    if m:
        month = next(
            (i for i, stems in enumerate(MONTH_STEMS, 1) if m.group(1).startswith(stems)), 0
        )
        if not month or len(m.group(1)) < 3:
            return None
        year = m.group(2)
    else:
        m = re.fullmatch(r"(\d{1,2})(?:[./ ](\d{2}|\d{4}))?", t)
        if not m or not 1 <= int(m.group(1)) <= 12:
            return None
        month, year = int(m.group(1)), m.group(2)
    if year is not None:
        return month_bounds(_full_year(year), month)
    # the latest such month that is not ahead
    return month_bounds(today.year if month <= today.month else today.year - 1, month)


def _quarter(t: str, today: date) -> Period | None:
    """«кв3», «3кв», «3 кв», «q3», «r3», «III кв» is not read; with a year: «кв3 25»."""
    words = "|".join(QUARTER_WORDS)
    m = re.fullmatch(rf"(?:(?:{words})\s*([1-4])|([1-4])\s*(?:{words}))\.?\s*(\d{{2}}|\d{{4}})?", t)
    if not m:
        return None
    quarter = int(m.group(1) or m.group(2))
    if m.group(3):
        return quarter_bounds(_full_year(m.group(3)), quarter)
    year = today.year if quarter <= quarter_of(today) else today.year - 1
    return quarter_bounds(year, quarter)


def _year(t: str) -> Period | None:
    if re.fullmatch(r"(19|20)\d{2}", t):
        return date(int(t), 1, 1), date(int(t), 12, 31)
    return None


def _day_period(t: str, today: date) -> Period | None:
    day = parse_date(t, today)
    return (day, day) if day is not None and not t.isdigit() else None
