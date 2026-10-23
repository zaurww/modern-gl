"""The date field of a form (D105): typed short, Enter or Tab; ↑ ↓ by a day; what is not
understood is red on Enter and dropped on Tab."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from modern_gl.desktop.widgets import date_edit, edited_date


@pytest.fixture
def form(qtbot):
    """A date field and a field after it, the window active: Tab has where to go."""
    page = QWidget()
    lay = QVBoxLayout(page)
    edit, after = date_edit(date(2026, 3, 5)), QLineEdit()
    lay.addWidget(edit)
    lay.addWidget(after)
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    qtbot.waitUntil(page.isActiveWindow)
    edit.setFocus(Qt.FocusReason.TabFocusReason)
    seen: list[QDate] = []
    edit.dateChanged.connect(seen.append)
    yield edit, after, seen
    del page  # held to the end: qtbot keeps only a weak reference


def typed(edit, text: str) -> None:
    """As if typed over the whole field (keyClicks breaks on Cyrillic under Windows)."""
    edit.setText(text)
    edit.setModified(True)
    edit.textEdited.emit(text)


def test_a_date_typed_as_digits(form):
    edit, after, seen = form
    assert edit.text() == "05.03.2026" and edit.selectedText() == "05.03.2026"
    QTest.keyClicks(edit, "17042026")  # replaces the selected date
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    assert edited_date(edit) == date(2026, 4, 17)
    assert edit.text() == "17.04.2026"
    assert after.hasFocus()
    assert seen == [QDate(2026, 4, 17)]


def test_a_bare_day_is_in_the_month_shown_and_words_are_from_today(form):
    edit, _after, _seen = form
    typed(edit, "9")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edited_date(edit) == date(2026, 3, 9)
    typed(edit, "вчера")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edited_date(edit) == date.today() - timedelta(days=1)


def test_arrows_move_by_a_day(form):
    edit, _after, seen = form
    QTest.keyClick(edit, Qt.Key.Key_Down)
    QTest.keyClick(edit, Qt.Key.Key_Down)
    QTest.keyClick(edit, Qt.Key.Key_Up)
    assert edited_date(edit) == date(2026, 3, 6)
    assert len(seen) == 3


def test_what_is_not_a_date(form):
    """Enter: red, the cursor stays, the date stays. Tab: the date shown again."""
    edit, after, seen = form
    typed(edit, "31.02")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edit.property("invalid") is True and edit.hasFocus()
    assert edited_date(edit) == date(2026, 3, 5)
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    assert after.hasFocus()
    assert edit.text() == "05.03.2026" and not edit.property("invalid")
    assert seen == []


def test_escape_drops_what_was_typed(form):
    edit, _after, seen = form
    typed(edit, "12")
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    assert edit.text() == "05.03.2026" and edited_date(edit) == date(2026, 3, 5)
    assert seen == []


def test_a_date_typed_counts_before_enter(form):
    """Ctrl+S right after typing: the date read is the typed one."""
    edit, _after, _seen = form
    typed(edit, "20.3")
    assert edited_date(edit) == date(2026, 3, 20)
    assert edit.text() == "20.03.2026"


def test_the_range_of_days(form):
    """The bank's line (a statement of 1–10 March): a day outside is not taken."""
    edit, _after, _seen = form
    edit.setDateRange(QDate(2026, 3, 1), QDate(2026, 3, 10))
    typed(edit, "15")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edit.property("invalid") is True
    assert edited_date(edit) == date(2026, 3, 5)
    edit.setDate(QDate(2026, 4, 1))
    assert edited_date(edit) == date(2026, 3, 10)  # set from outside: to the nearest end
