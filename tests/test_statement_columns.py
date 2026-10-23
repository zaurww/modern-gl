"""The columns of a financial statement (D107): which periods, how figures add, the
difference and the percent of a comparison."""

from __future__ import annotations

from datetime import date

from modern_gl.reporting.columns import (
    MONTHS,
    ONE,
    PREVIOUS,
    QUARTERS,
    YEAR_AGO,
    Amounts,
    column_periods,
    difference,
    percent,
    total,
)


def d(text: str) -> date:
    return date.fromisoformat(text)


def p(first: str, last: str) -> tuple[date, date]:
    return d(first), d(last)


def test_one_period_is_one_column():
    assert column_periods(ONE, p("2026-01-01", "2026-03-31")) == [p("2026-01-01", "2026-03-31")]


def test_months_cut_to_the_period_and_the_whole_last():
    """«сг» on 23 October: January … October, the October column up to the 23rd."""
    periods = column_periods(MONTHS, p("2026-01-01", "2026-10-23"))
    assert len(periods) == 11
    assert periods[0] == p("2026-01-01", "2026-01-31")
    assert periods[1] == p("2026-02-01", "2026-02-28")
    assert periods[9] == p("2026-10-01", "2026-10-23")
    assert periods[10] == p("2026-01-01", "2026-10-23")  # «Итого»


def test_one_month_by_months_is_just_the_month():
    assert column_periods(MONTHS, p("2026-10-01", "2026-10-31")) == [p("2026-10-01", "2026-10-31")]


def test_more_than_thirteen_months_go_by_quarters():
    periods = column_periods(MONTHS, p("2025-01-01", "2026-06-30"))
    assert periods[0] == p("2025-01-01", "2025-03-31")
    assert periods[5] == p("2026-04-01", "2026-06-30")
    assert len(periods) == 7  # six quarters and the whole


def test_quarters_across_a_year():
    periods = column_periods(QUARTERS, p("2025-11-15", "2026-02-10"))
    assert periods == [
        p("2025-11-15", "2025-12-31"),
        p("2026-01-01", "2026-02-10"),
        p("2025-11-15", "2026-02-10"),
    ]


def test_compared_with_the_period_before_and_a_year_before():
    assert column_periods(PREVIOUS, p("2026-07-01", "2026-09-30")) == [
        p("2026-07-01", "2026-09-30"),
        p("2026-04-01", "2026-06-30"),
    ]
    assert column_periods(YEAR_AGO, p("2028-02-01", "2028-02-29")) == [
        p("2028-02-01", "2028-02-29"),
        p("2027-02-01", "2027-02-28"),  # the end of a month stays the end
    ]
    assert column_periods(YEAR_AGO, p("2026-01-01", "2026-10-23")) == [
        p("2026-01-01", "2026-10-23"),
        p("2025-01-01", "2025-10-23"),
    ]


def test_amounts_add_as_figures():
    a, b = Amounts((100, -50)), Amounts((1, 2))
    assert a + b == Amounts((101, -48))
    assert a - b == Amounts((99, -52))
    assert -1 * a == Amounts((-100, 50))
    assert 0 + a == a  # a defaultdict(int) and sum() start from 0
    assert Amounts() + a == a  # empty is zero in every column
    assert total([a, b, Amounts.at(1, 2, 10)]) == Amounts((101, -38))
    assert not Amounts((0, 0)) and Amounts((0, 5))
    assert Amounts((7,)) == 7  # one column compares as its figure
    assert Amounts((3,))[1] == 0  # past the end is zero


def test_difference_and_percent():
    """120.00 against 100.00: +20.00, +20 %; 50 against 150: −100, −66.67 %."""
    assert difference(Amounts((12_000, 10_000))) == 2_000
    assert percent(Amounts((12_000, 10_000))) == 2_000  # 20.00 %
    assert percent(Amounts((50, 150))) == -6_667  # −66.666… → −66.67 %
    assert percent(Amounts((-300, -200))) == -5_000  # the base by its size: −50 %
    assert percent(Amounts((100, 0))) is None
