"""Periods and dates typed short (D105). Today is Friday 23 October 2026."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.domain.period_input import describe, parse_date, parse_period, shift

TODAY = date(2026, 10, 23)


def d(text: str) -> date:
    return date.fromisoformat(text)


@pytest.mark.parametrize(
    ("typed", "period"),
    [
        ("м", ("2026-10-01", "2026-10-31")),
        ("нед", ("2026-10-19", "2026-10-25")),  # Monday to Sunday
        ("bu həftə", ("2026-10-19", "2026-10-25")),
        ("пн", ("2026-10-12", "2026-10-18")),
        ("lw", ("2026-10-12", "2026-10-18")),
        ("Bu ay", ("2026-10-01", "2026-10-31")),
        ("пм", ("2026-09-01", "2026-09-30")),
        ("ka", ("2026-09-01", "2026-09-30")),
        ("keçən ay", ("2026-09-01", "2026-09-30")),
        ("kecen ay", ("2026-09-01", "2026-09-30")),
        ("кв", ("2026-10-01", "2026-12-31")),
        ("rüb", ("2026-10-01", "2026-12-31")),
        ("3r", ("2026-07-01", "2026-09-30")),
        ("3rüb", ("2026-07-01", "2026-09-30")),
        ("3rüb 2025", ("2025-07-01", "2025-09-30")),  # as the field shows it in Azerbaijani
        ("пк", ("2026-07-01", "2026-09-30")),
        ("г", ("2026-01-01", "2026-12-31")),
        ("пг", ("2025-01-01", "2025-12-31")),
        ("сг", ("2026-01-01", "2026-10-23")),
        ("İLB", ("2026-01-01", "2026-10-23")),
        ("ск", ("2026-10-01", "2026-10-23")),
        ("см", ("2026-10-01", "2026-10-23")),
        ("окт", ("2026-10-01", "2026-10-31")),
        ("Октябрь", ("2026-10-01", "2026-10-31")),
        ("okt 25", ("2025-10-01", "2025-10-31")),
        ("дек", ("2025-12-01", "2025-12-31")),  # not ahead: last December
        ("fev", ("2026-02-01", "2026-02-28")),
        ("мая 2024", ("2024-05-01", "2024-05-31")),
        # English (D105): the same in any language of the interface
        ("this month", ("2026-10-01", "2026-10-31")),
        ("lm", ("2026-09-01", "2026-09-30")),
        ("Last month", ("2026-09-01", "2026-09-30")),
        ("q3", ("2026-07-01", "2026-09-30")),
        ("lq", ("2026-07-01", "2026-09-30")),
        ("ytd", ("2026-01-01", "2026-10-23")),
        ("qtd", ("2026-10-01", "2026-10-23")),
        ("mtd", ("2026-10-01", "2026-10-23")),
        ("ly", ("2025-01-01", "2025-12-31")),
        ("Oct", ("2026-10-01", "2026-10-31")),
        ("jan 25", ("2025-01-01", "2025-01-31")),
        ("aug", ("2026-08-01", "2026-08-31")),
        ("December 2025", ("2025-12-01", "2025-12-31")),
        ("10", ("2026-10-01", "2026-10-31")),
        ("3", ("2026-03-01", "2026-03-31")),
        ("11", ("2025-11-01", "2025-11-30")),
        ("10.25", ("2025-10-01", "2025-10-31")),
        ("2.2024", ("2024-02-01", "2024-02-29")),
        ("кв3", ("2026-07-01", "2026-09-30")),
        ("3кв", ("2026-07-01", "2026-09-30")),
        ("3 кв 2025", ("2025-07-01", "2025-09-30")),
        ("q1", ("2026-01-01", "2026-03-31")),
        ("r2 25", ("2025-04-01", "2025-06-30")),
        ("кв4", ("2026-10-01", "2026-12-31")),
        ("2025", ("2025-01-01", "2025-12-31")),
        ("1.10-15.10", ("2026-10-01", "2026-10-15")),
        ("1.10 — 15.10.25", ("2025-10-01", "2025-10-15")),
        ("20.12.25..10.01.26", ("2025-12-20", "2026-01-10")),
        ("15.10", ("2026-10-15", "2026-10-15")),
        ("вчера", ("2026-10-22", "2026-10-22")),
    ],
)
def test_a_period_typed_short(typed, period):
    assert parse_period(typed, TODAY) == (d(period[0]), d(period[1]))


@pytest.mark.parametrize(
    "typed",
    ["", "  ", "13", "ок", "кв5", "15.10-1.10", "32.10", "abc", "1.10-5.10.99999999999999999999"],
)
def test_what_is_not_a_period(typed):
    assert parse_period(typed, TODAY) is None


@pytest.mark.parametrize(
    ("typed", "day"),
    [
        ("5", "2026-10-05"),
        ("5.9", "2026-09-05"),
        ("5/9", "2026-09-05"),
        ("5.9.25", "2025-09-05"),
        ("05.09.2025", "2025-09-05"),
        ("050925", "2025-09-05"),
        ("05092025", "2025-09-05"),
        ("сегодня", "2026-10-23"),
        ("bu gün", "2026-10-23"),
        ("вчера", "2026-10-22"),
        ("dünən", "2026-10-22"),
        ("today", "2026-10-23"),
        ("Yesterday", "2026-10-22"),
        ("tomorrow", "2026-10-24"),
        ("завтра", "2026-10-24"),
        ("+3", "2026-10-26"),
        ("-1", "2026-10-22"),
    ],
)
def test_a_date_typed_short(typed, day):
    assert parse_date(typed, TODAY) == d(day)


def test_a_bare_day_is_in_the_month_shown():
    assert parse_date("5", TODAY, shown=date(2026, 3, 17)) == date(2026, 3, 5)


@pytest.mark.parametrize(
    "typed", ["", "31.02", "0", "5.13", "завтра утром", "5.10.99999999999999999999", "9" * 20]
)
def test_what_is_not_a_date(typed):
    assert parse_date(typed, TODAY) is None


def test_how_a_period_is_shown():
    assert describe((d("2026-10-01"), d("2026-10-31"))) == "Октябрь 2026"
    assert describe((d("2026-07-01"), d("2026-09-30"))) == "3 квартал 2026"
    assert describe((d("2026-01-01"), d("2026-12-31"))) == "2026"
    assert describe((d("2026-10-05"), d("2026-10-05"))) == "05.10.2026"
    assert describe((d("2026-10-01"), d("2026-10-15"))) == "01.10 — 15.10.2026"
    assert describe((d("2025-12-29"), d("2026-01-04"))) == "29.12.2025 — 04.01.2026"


def test_the_period_field_of_a_report(qtbot):
    """One field: type «пм» and Enter; ↑ — the month before; what is not understood is
    marked and the period stays; Esc drops what was typed."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from modern_gl.desktop.period_field import PeriodField

    field = PeriodField((d("2026-10-01"), d("2026-10-31")), TODAY)
    qtbot.addWidget(field)
    field.show()
    assert field.edit.text() == "Октябрь 2026"
    seen = []
    field.changed.connect(lambda: seen.append(field.period()))

    def typed(text: str) -> None:
        field.edit.setText(text)
        field.edit.setModified(True)
        field.edit.textEdited.emit(text)
        QTest.keyClick(field.edit, Qt.Key.Key_Return)

    typed("пм")
    assert field.period() == (d("2026-09-01"), d("2026-09-30"))
    assert field.edit.text() == "Сентябрь 2026"
    QTest.keyClick(field.edit, Qt.Key.Key_Up)
    assert field.period() == (d("2026-08-01"), d("2026-08-31"))
    typed("кв3")
    assert field.edit.text() == "3 квартал 2026"
    typed("что-то")
    assert field.edit.property("invalid") is True
    assert field.period() == (d("2026-07-01"), d("2026-09-30"))
    QTest.keyClick(field.edit, Qt.Key.Key_Escape)
    assert field.edit.text() == "3 квартал 2026" and not field.edit.property("invalid")
    assert len(seen) == 3  # пм, ↑, кв3 — the wrong text changed nothing


def test_the_arrows_move_by_the_same_kind_of_period():
    october = (d("2026-10-01"), d("2026-10-31"))
    assert shift(october, -1) == (d("2026-09-01"), d("2026-09-30"))
    assert shift(october, 3) == (d("2027-01-01"), d("2027-01-31"))
    quarter = (d("2026-07-01"), d("2026-09-30"))
    assert shift(quarter, 1) == (d("2026-10-01"), d("2026-12-31"))
    year = (d("2026-01-01"), d("2026-12-31"))
    assert shift(year, -1) == (d("2025-01-01"), d("2025-12-31"))
    week = (d("2026-10-19"), d("2026-10-25"))
    assert shift(week, 1) == (d("2026-10-26"), d("2026-11-01"))


def test_the_period_with_the_mouse(qtbot):
    """▾ opens the panel: the chosen months are blue; a month, Shift — a stretch of
    months, a usual period, a quarter of the year before, the exact dates (D105)."""
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtTest import QTest

    from modern_gl.desktop.period_field import PeriodField

    field = PeriodField((d("2026-10-01"), d("2026-10-31")), TODAY)
    qtbot.addWidget(field)
    field.show()

    def panel():
        field.show_presets()
        return field.window_shown

    window = panel()
    assert [b.isChecked() for b in window.month_buttons].index(True) == 9  # October
    assert window.preset_buttons["м"].isChecked()
    window.month_buttons[2].click()  # March
    assert field.period() == (d("2026-03-01"), d("2026-03-31"))
    assert not window.isVisible()

    panel().choose_month(5, extend=True)  # Shift+click on May: March … May
    assert field.period() == (d("2026-03-01"), d("2026-05-31"))
    assert field.edit.text() == "01.03 — 31.05.2026"

    panel().preset_buttons["пм"].click()
    assert field.period() == (d("2026-09-01"), d("2026-09-30"))

    window = panel()
    window._step_year(-1)
    assert window.year_label.text() == "2025"
    window.quarter_buttons[1].click()
    assert field.period() == (d("2025-04-01"), d("2025-06-30"))

    window = panel()
    window.first.setDate(QDate(2026, 1, 10))
    window.last.setDate(QDate(2026, 1, 20))
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert field.period() == (d("2026-01-10"), d("2026-01-20"))
