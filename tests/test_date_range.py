"""A range of dates in one place (review, session 47): the year once when both ends are
in it, on both ends across a new year — the period field, the period bar, the e-qaimə
reconciliation and the bank's statements alike."""

from __future__ import annotations

from datetime import date

from modern_gl.application.bank import BankStatement
from modern_gl.desktop.bank_page.levels import period_text
from modern_gl.desktop.period_bar import period_dates
from modern_gl.domain.dates import date_range


def test_a_range_names_the_year_once_or_on_both_ends():
    assert date_range("2026-10-01", "2026-10-15") == "01.10 — 15.10.2026"
    assert date_range("2025-12-29", "2026-01-04") == "29.12.2025 — 04.01.2026"
    assert date_range("2026-10-20", "2026-10-20") == "20.10.2026"
    assert date_range(date(2026, 10, 13), date(2026, 10, 19), "–") == "13.10–19.10.2026"
    assert period_dates(date(2025, 12, 29), date(2026, 1, 4)) == "29.12.2025–04.01.2026"


def test_a_bank_statement_across_a_new_year_shows_both_years():
    """Was «29.12 — 04.01.2026»: the start looked like 29.12.2026."""
    statement = BankStatement(None, "2025-12-29", "2026-01-04", 0, 0, 0, 0, 0, None)
    assert period_text(statement) == "29.12.2025 — 04.01.2026"
