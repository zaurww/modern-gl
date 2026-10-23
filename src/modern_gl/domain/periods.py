"""Periods chosen at a click: «Вчера», «Эта неделя», «Прошлая неделя», «Этот месяц»,
«Прошлый месяц» — for the portal import and the morning reconciliation (D53)."""

from __future__ import annotations

from datetime import date, timedelta

from modern_gl.domain.dates import month_days

DAY, WEEK, LAST_WEEK, MONTH, LAST_MONTH = "day", "week", "last_week", "month", "last_month"
SPANS = (DAY, WEEK, LAST_WEEK, MONTH, LAST_MONTH)


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-09' -> 1 and 30 September 2026."""
    return month_days(int(month[:4]), int(month[5:7]))


def full_month(date_from: date, date_to: date) -> str | None:
    """'YYYY-MM' when the period is exactly one calendar month, else None."""
    month = f"{date_from:%Y-%m}"
    return month if (date_from, date_to) == month_bounds(month) else None


def quick_period(span: str, today: date, through_today: bool = False) -> tuple[date, date]:
    """«Вчера»: yesterday, on a Monday Friday to Sunday. «Эта неделя», «Этот месяц»: from
    Monday / the 1st to yesterday — a morning check looks at finished days — or to today
    (`through_today`, the import); on a Monday / the 1st it is today alone. «Прошлая
    неделя», «Прошлый месяц»: the whole calendar week / month before this one."""
    yesterday = today - timedelta(days=1)
    last = today if through_today else yesterday
    monday = today - timedelta(days=today.weekday())
    if span == DAY:
        return (today - timedelta(days=3) if today.weekday() == 0 else yesterday), yesterday
    if span == WEEK:
        return monday, max(last, monday)
    if span == LAST_WEEK:
        return monday - timedelta(days=7), monday - timedelta(days=1)
    first = today.replace(day=1)
    if span == MONTH:
        return first, max(last, first)
    return month_bounds(f"{first - timedelta(days=1):%Y-%m}")


def span_of(date_from: date, date_to: date, today: date) -> str | None:
    """The quick period a period was chosen as, judged by its shape: a mark made on
    another day still tells how the company is usually reconciled. None: by hand."""
    days = (date_to - date_from).days + 1
    if days == 1 or (days == 3 and date_from.weekday() == 4):
        return DAY  # a day, or Friday to Sunday
    if date_from.weekday() == 0 and days <= 7:
        return LAST_WEEK if days == 7 else WEEK
    if date_from.day == 1:
        if full_month(date_from, date_to) and date_to < today.replace(day=1):
            return LAST_MONTH
        return MONTH
    return None
