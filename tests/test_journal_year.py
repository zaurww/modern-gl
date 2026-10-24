"""The journal shows one year, not every document (debt 6): the working date's year by
default, another from the menu, «every year» on request; a saved document brings its year."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import document_year, document_years
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.journal_page import JournalPage, shown_year
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure.db import connect


def test_the_year_shown():
    years = [2026, 2025, 2023]
    assert shown_year([], 2026, 2026) is None
    assert shown_year(years, 2023, 2026) == 2023  # asked for
    assert shown_year(years, None, 2025) == 2025  # the working date's
    assert shown_year(years, 2024, 2025) == 2025  # asked for a year without documents
    assert shown_year(years, None, 2027) == 2026  # working ahead: the latest
    assert shown_year(years, None, 2020) == 2023  # working behind: the earliest
    assert shown_year(years, None, 2024) == 2025  # a gap: the nearest, the latest of two


@pytest.fixture
def old_doc(tmp_path):
    """The demo company (13 documents of 2026) and a draft of 2024."""
    conn = connect(tmp_path / "ДЕМО ООО.gl")
    ledger = Ledger(conn)
    create_demo_company(ledger)
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    doc_id = ledger.create_draft(cid, "2024-12-31", [], "Старый")
    assert document_years(conn, cid) == [2026, 2025, 2024]
    assert document_year(conn, cid, doc_id) == 2024
    assert document_year(conn, cid, doc_id + 100) is None
    conn.close()
    return doc_id


@pytest.fixture
def window(qtbot, tmp_path, old_doc):
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 3, 5)
    win.show_place(("journal",))
    win.show()
    yield win
    win.session.background.wait()
    win.shutdown()


def memos(page: JournalPage) -> list[str]:
    return [d.memo for d in page.model.docs]


def test_the_journal_shows_the_working_year(window, old_doc):
    page = window.stack.currentWidget()
    assert isinstance(page, JournalPage)
    assert page.year == 2026
    assert page.model.rowCount() == 13
    assert "Старый" not in memos(page)
    assert page.year_button.isVisibleTo(page) and page.year_button.text() == "2026"
    texts = [item[0] for item in page._year_items() if item]
    assert texts == ["2026", "2025", "2024", "Все годы"]

    page.show_year(2024)
    assert memos(page) == ["Старый"]
    page.show_year(None)
    assert page.model.rowCount() == 14 and page.year_button.text() == "Все годы"
    page.refresh()
    assert page.model.rowCount() == 14  # «every year» stays chosen

    page.show_year(2026)
    page.refresh(select_id=old_doc)  # saved in its form: the journal goes to its year
    assert page.year == 2024 and page._current_id() == old_doc


def test_a_large_company_reads_the_year_in_the_background(window, qtbot):
    page = window.stack.currentWidget()
    window.session.large = True
    page.show_year(2024)
    qtbot.waitUntil(lambda: memos(page) == ["Старый"])
    assert page.year == 2024
