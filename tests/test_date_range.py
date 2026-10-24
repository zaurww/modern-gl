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


def test_the_day_after():
    from modern_gl.domain.dates import next_day

    assert next_day("2026-12-31") == "2027-01-01"
    assert next_day(date(2028, 2, 28)) == "2028-02-29"


def test_a_month_with_a_capital_letter_in_both_languages():
    """Azerbaijani capitals: «iyun» is «İyun», not «Iyun» (D56)."""
    from modern_gl.domain.dates import month_title
    from modern_gl.i18n import set_language

    set_language("az")
    try:
        assert month_title("2026-06") == "İyun 2026"
        assert month_title("2026-03") == "Mart 2026"
    finally:
        set_language("ru")
    assert month_title("2026-06") == "Июнь 2026"
