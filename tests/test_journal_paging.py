"""The journal of a large company is read in pages (D-new-journal-paging): 500 documents
around the one shown, more as the list is scrolled; the search is in the query, so it finds
a document that was not read yet, letters folded (İ/ş = i/s)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.catalog import Catalog
from modern_gl.application.journal import (
    PAGE,
    JournalFilter,
    documents_after,
    documents_before,
    key_of,
)
from modern_gl.application.queries import list_documents
from modern_gl.desktop import theme
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.db import transaction

GENERATED = 2_100
YEAR = ("2026-01-01", "2026-12-31")


@pytest.fixture
def big(demo):
    """The test company (6 documents of 2026) and 2 100 more over the year, the first of
    them «Şirkətin ilk ödənişi», the last «Yekun ödəniş»."""
    led, cid = demo.ledger, demo.company_id
    with transaction(led.conn):
        for i in range(GENERATED):
            day = date(2026, 1, 1) + timedelta(days=i * 364 // GENERATED)
            memo = {0: "Şirkətin ilk ödənişi", GENERATED - 1: "Yekun ödəniş"}.get(i, f"Gen {i}")
            led.post_new(cid, day, [demo.p("721", "221", "1.00")], memo)
    return demo


def test_the_pages_put_together_are_the_journal(big):
    conn, cid = big.ledger.conn, big.company_id
    f = JournalFilter(cid, *YEAR)
    whole = list_documents(conn, cid, *YEAR)
    assert len(whole) == GENERATED + 6

    last = documents_before(conn, f, None)
    assert len(last.docs) == PAGE and last.more
    assert last.docs == whole[-PAGE:]  # the end of the year, in the journal's order
    read = last.docs
    while (older := documents_before(conn, f, key_of(read[0]))).docs:
        read = older.docs + read
    assert read == whole and not older.more

    first = documents_after(conn, f, ("2025-12-31", 0))
    assert first.docs == whole[:PAGE] and first.more
    middle = key_of(whole[1000])
    upto = documents_before(conn, f, middle, including=True)
    assert upto.docs == whole[1000 - PAGE + 1 : 1001]
    assert documents_after(conn, f, middle).docs == whole[1001 : 1001 + PAGE]


def test_the_search_is_over_the_whole_year(big):
    conn, cid = big.ledger.conn, big.company_id
    found = documents_before(conn, JournalFilter(cid, *YEAR, "sirketin ILK odenis"), None)
    assert [d.memo for d in found.docs] == ["Şirkətin ilk ödənişi"] and not found.more
    by_number = documents_before(conn, JournalFilter(cid, *YEAR, "1999"), None).docs
    assert 1999 in [d.number for d in by_number] and len(by_number) == 2  # and «Gen 1999»
    by_date = documents_before(conn, JournalFilter(cid, *YEAR, "05.01.2026"), None).docs
    assert by_date and {d.doc_date for d in by_date} == {"2026-01-05"}
    nothing = documents_before(conn, JournalFilter(cid, *YEAR, "50%_"), None)
    assert nothing.docs == []  # % and _ are letters, not patterns


@pytest.fixture
def page(qtbot, big):
    theme.apply(QApplication.instance())
    conn, cid = big.ledger.conn, big.company_id
    s = Session(conn, big.ledger, cid, "ООО Тест", Catalog(conn, cid), notify=lambda m: None)
    s.working_date = date(2026, 6, 1)
    journal = JournalPage(s)
    qtbot.addWidget(journal)
    journal.resize(1000, 700)
    journal.show()
    qtbot.waitExposed(journal)
    return journal


def test_the_journal_opens_on_the_last_page(page, big):
    whole = list_documents(big.ledger.conn, big.company_id, *YEAR)
    assert page.model.rowCount() == PAGE
    assert page.model.docs == whole[-PAGE:]
    assert page._current_id() == whole[-1].id  # the newest chosen, as before

    bar = page.table.verticalScrollBar()
    bar.setValue(bar.minimum())  # scrolled to the top: the older page comes in
    assert page.model.rowCount() == 2 * PAGE
    assert page.model.docs == whole[-2 * PAGE :]
    assert page._current_id() == whole[-1].id
    top = page.table.indexAt(page.table.viewport().rect().topLeft()).row()
    assert top == PAGE  # the rows on the screen stayed where they were
    for _ in range(5):
        bar.setValue(bar.minimum())
    assert page.model.docs == whole and not page.model.older


def test_a_document_shown_brings_its_page_and_the_newer_come_on_scrolling(page, big):
    whole = list_documents(big.ledger.conn, big.company_id, *YEAR)
    page.refresh(select_id=whole[700].id)  # saved in its form
    assert page._current_id() == whole[700].id
    assert page.model.docs[0] == whole[700 - PAGE + 1]
    bar = page.table.verticalScrollBar()
    for _ in range(5):  # scrolled to the end: the view asks the model for more (fetchMore)
        bar.setValue(bar.maximum() - 1)
        bar.setValue(bar.maximum())
    assert page.model.docs == whole[700 - PAGE + 1 :]


def test_the_search_finds_what_was_not_read(page, big):
    assert "Şirkətin ilk ödənişi" not in [d.memo for d in page.model.docs]
    page.search.setText("şirkətin İLK")
    assert [d.memo for d in page.model.docs] == ["Şirkətin ilk ödənişi"]
    page.search.setText("sirketin ilk odenis")  # a keyboard without Azerbaijani letters
    assert [d.memo for d in page.model.docs] == ["Şirkətin ilk ödənişi"]
    found = page._current_id()
    page.search.setText("нет такого")
    assert page.model.rowCount() == 0 and page.stack.currentWidget() is page.table
    page.search.setText("sirketin")
    page.search.clear()  # the whole year again, on the document found
    assert page._current_id() == found
    assert page.model.docs[0].memo == "Şirkətin ilk ödənişi" and page.model.newer
