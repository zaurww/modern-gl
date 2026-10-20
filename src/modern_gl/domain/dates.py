from __future__ import annotations

from datetime import date, datetime


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
