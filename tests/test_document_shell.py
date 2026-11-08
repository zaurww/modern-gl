"""One frame for every document form (D213, step 2): «⋯» in the head with the story of
the postings; the journal's document deletes and unposts with buttons under the form,
as the bank, the conversion and the warehouse do. Demo company: GL №2 is purchase №1,
GL №1 a journal document, GL №13 a journal draft."""

from __future__ import annotations

from typing import Any

from modern_gl.application.queries import document_by_number
from modern_gl.desktop.document_shell import DocumentShell


def _open(window, number: int) -> Any:
    s = window.company.open_session
    window.open_document(document_by_number(s.conn, s.company_id, number))
    page = window.stack.currentWidget()
    assert isinstance(page, DocumentShell)
    return page


def _menu(page) -> list[str]:
    return [item[0] for item in page.menu_items() if item]


def test_a_purchase_shows_the_story_of_its_postings(demo_window):
    page = _open(demo_window, 2)
    assert page.title() == "Покупка №1"
    assert "История изменений" in _menu(page)
    assert not page.btn_more.isHidden()


def test_a_journal_document_deletes_and_unposts_with_buttons(demo_window):
    posted = _open(demo_window, 1)
    assert "История изменений" in _menu(posted)
    assert "Удалить" not in _menu(posted) and "Отменить проведение" not in _menu(posted)
    assert not posted.btn_delete.isHidden() and not posted.btn_unpost.isHidden()
    draft = _open(demo_window, 13)
    assert not draft.btn_delete.isHidden() and draft.btn_unpost.isHidden()


def test_a_journal_document_made_by_a_module_is_corrected_there(demo_window):
    demo_window.show_document(
        document_by_number(
            demo_window.company.open_session.conn, demo_window.company.open_session.company_id, 2
        )
    )
    page = demo_window.stack.currentWidget()
    assert page.btn_delete.isHidden() and page.btn_unpost.isHidden()
    assert not page.btn_source.isHidden()
