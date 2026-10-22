"""Who entered and who posted a document (D82): read from the audit trail."""

from modern_gl.application.authorship import (
    DocumentAuthors,
    authors_text,
    document_authors,
    journal_authors,
    local_time,
)
from modern_gl.application.ledger import Ledger
from tests.conftest import build_demo


def test_who_entered_and_who_posted(conn):
    demo = build_demo(Ledger(conn, actor="Aynur"))
    cid = demo.company_id
    draft = Ledger(conn, actor="Aynur").create_draft(cid, "2026-03-01", [demo.p("721", "221", "5")])
    Ledger(conn, actor="Zaur").post(cid, draft)

    authors = document_authors(conn, cid, draft)

    assert authors is not None
    assert (authors.entered_by, authors.posted_by) == ("Aynur", "Zaur")
    assert authors.entered_at and authors.posted_at


def test_a_draft_has_no_poster_and_unposting_forgets_it(conn):
    demo = build_demo(Ledger(conn, actor="Aynur"))
    cid = demo.company_id
    doc = demo.docs[0]
    assert document_authors(conn, cid, doc).posted_by == "Aynur"  # post_new: entered and posted
    Ledger(conn, actor="Zaur").unpost(cid, doc)

    authors = document_authors(conn, cid, doc)

    assert (authors.entered_by, authors.posted_by) == ("Aynur", None)


def test_reposted_by_another_shows_the_last_one(conn):
    demo = build_demo(Ledger(conn, actor="Aynur"))
    cid = demo.company_id
    doc = demo.docs[1]
    zaur = Ledger(conn, actor="Zaur")
    zaur.unpost(cid, doc)
    zaur.post(cid, doc)

    assert document_authors(conn, cid, doc).posted_by == "Zaur"
    assert journal_authors(conn, cid)[doc] == "Zaur"
    assert journal_authors(conn, cid)[demo.docs[0]] == "Aynur"


def test_another_company_is_not_mixed_in(conn):
    one = build_demo(Ledger(conn, actor="Aynur"), "One")
    two = build_demo(Ledger(conn, actor="Zaur"), "Two")
    assert set(journal_authors(conn, one.company_id).values()) == {"Aynur"}
    assert document_authors(conn, one.company_id, two.docs[0]) is None


def test_the_line_in_the_document_head():
    utc = "2026-01-15T10:32:00+00:00"
    shown = local_time(utc)
    assert shown.startswith("15.01.2026")
    same = DocumentAuthors("Aynur", utc, "Aynur", utc)
    assert authors_text(same)[0] == f"Провёл Aynur · {shown}"
    other = DocumentAuthors("Aynur", utc, "Zaur", utc)
    line, tip = authors_text(other)
    assert line == f"Ввёл Aynur · провёл Zaur · {shown}"
    assert tip == f"Ввёл: Aynur, {shown}\nПровёл: Zaur, {shown}"
    assert authors_text(DocumentAuthors("Aynur", utc, None, None))[0] == f"Ввёл Aynur · {shown}"
