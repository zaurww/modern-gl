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


def test_a_purchase_is_copied_into_a_new_purchase(demo_window):
    """Purchase №1: 120 packs of paper for 1 200.00, ƏDV 216.00, e-qaimə MT2601001842 —
    the copy is a new purchase draft with the same lines and sums, without the e-qaimə."""
    source = _open(demo_window, 2)
    copy = dict(i for i in source.menu_items() if i)["Копировать"]
    copy()
    page: Any = demo_window.stack.currentWidget()
    assert page is not source and page.doc is None and page.doc_type == "receipt"
    assert page.save(post=False)
    doc: Any = page.doc  # saved: read again
    assert doc.status == "draft" and doc.invoice == "" and doc.number != source.doc.number
    assert [(ln.quantity, ln.amount, ln.vat_amount) for ln in doc.lines] == [
        (120_000_000, 120000, 21600)
    ]
    assert doc.memo == source.doc.memo


def test_f9_on_a_purchase_in_the_journal_copies_the_purchase(demo_window):
    s = demo_window.company.open_session
    demo_window.copy_document(document_by_number(s.conn, s.company_id, 2))
    page = demo_window.stack.currentWidget()
    assert page.doc is None and page.doc_type == "receipt"
    assert page.title().startswith("Новое: Покупка")


def test_ctrl_shift_enter_posts_a_purchase_and_opens_a_new_one(demo_window):
    source = _open(demo_window, 2)
    source.post_and_new()
    page: Any = demo_window.stack.currentWidget()
    assert page is not source and page.doc is None and page.doc_type == "receipt"
