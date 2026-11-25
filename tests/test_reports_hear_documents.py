"""A report left open shows what was posted since: a purchase, a batch's expenses or a
journal document saved tells every open page that postings changed (found in a live test:
the trial balance kept the figures it had before two warehouse documents were posted)."""

from __future__ import annotations

from modern_gl.desktop.document_page import DocumentPage


def test_a_saved_warehouse_document_reaches_the_open_pages(demo_window, monkeypatch):
    win = demo_window
    row = win.session.conn.execute(
        "SELECT id, gl_document_id FROM inventory_documents "
        "WHERE company_id = ? AND status = 'posted' ORDER BY id LIMIT 1",
        (win.session.company_id,),
    ).fetchone()
    heard: list[int] = []
    monkeypatch.setattr(win.page_stack, "postings_changed", heard.append)
    win.open_inventory_document(row["id"])
    page = win.stack.currentWidget()
    page.saved.emit(row["id"])
    assert heard == [row["gl_document_id"]]  # the journal's document, not the warehouse's


def test_a_saved_journal_document_reaches_the_open_pages(demo_window, monkeypatch):
    win = demo_window
    doc_id = win.session.conn.execute(
        "SELECT d.id FROM documents d WHERE d.company_id = ? AND d.status = 'posted' "
        "AND NOT EXISTS (SELECT 1 FROM document_owners o WHERE o.company_id = d.company_id "
        "AND o.document_id = d.id) ORDER BY d.id LIMIT 1",
        (win.session.company_id,),
    ).fetchone()["id"]
    heard: list[int] = []
    monkeypatch.setattr(win.page_stack, "postings_changed", heard.append)
    win.open_document(doc_id)
    page = win.stack.currentWidget()
    assert isinstance(page, DocumentPage)
    page.saved.emit(doc_id)
    assert heard == [doc_id]
