from __future__ import annotations

from datetime import date, datetime


def iso_date(value: date | str) -> str:
    """Normalize a date or 'YYYY-MM-DD' string; rejects datetimes and garbage."""
    if isinstance(value, datetime):
        raise TypeError("expected a date, got a datetime")
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()
