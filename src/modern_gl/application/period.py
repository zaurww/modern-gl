"""Closing the period (D5, D94): up to which day nothing is changed in place any more —
what the window shows before the period is closed or opened again. Only reading; the
change itself is `Ledger.set_closed_through` (audited)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from modern_gl.application.common import company_row
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class PeriodEnd:
    title: str  # Russian, for tr()
    day: date


def closed_through(conn: Connection, company_id: int) -> str | None:
    """The last closed day (ISO); None: every period is open."""
    return company_row(conn, company_id)["closed_through"]


def drafts_through(conn: Connection, company_id: int, day: date | str) -> int:
    """Drafts of the books dated up to the day: once it is closed they cannot be posted."""
    return conn.execute(
        "SELECT COUNT(*) FROM documents WHERE company_id = ? AND status = 'draft' "
        "AND doc_date <= ?",
        (company_id, iso_date(day)),
    ).fetchone()[0]


def period_ends(working: date) -> list[PeriodEnd]:
    """What one usually closes: the end of the last month, quarter and year before the
    working date (the same day may be all three — then it is offered once)."""
    month = working.replace(day=1) - timedelta(days=1)
    quarter_start = date(working.year, 3 * ((working.month - 1) // 3) + 1, 1)
    quarter = quarter_start - timedelta(days=1)
    year = date(working.year - 1, 12, 31)
    ends: list[PeriodEnd] = []
    for title, day in (
        ("Конец прошлого месяца", month),
        ("Конец прошлого квартала", quarter),
        ("Конец прошлого года", year),
    ):
        if all(e.day != day for e in ends):
            ends.append(PeriodEnd(title, day))
    return ends
