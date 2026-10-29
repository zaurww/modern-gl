"""«Проводки» under a module's document form (desktop/posting_preview.py): what it posts,
before «Провести» and after. Hand-calculated on the bank example of tests/helpers/bank_ui:
a payment to ALFA of 1 180.00 — Dt 60.1 [ALFA MMC, Договор 1] / Ct 51 [Kapital AZN]."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QKeySequence, QShortcut

from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.posting_peek import PostingsPeek
from modern_gl.desktop.posting_preview import OPEN_KEY
from modern_gl.desktop.preferences import prefs
from modern_gl.domain.company import STOCK_ONLY
from tests.helpers.bank_ui import new_page, pay_alfa, type_text

pytestmark = pytest.mark.questions("Yes")


@pytest.fixture
def session(bank_session):
    return bank_session


def counts(conn):
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("documents", "postings", "bank_operations", "audit_events")
    )


def shown(panel) -> list[tuple[str, str, str, str, int]]:
    return [
        (r.debit, ", ".join(r.debit_subconto), r.credit, ", ".join(r.credit_subconto), r.amount)
        for r in panel.model.rows
    ]


def test_a_new_payment_shows_what_it_would_post(qtbot, session):
    page = new_page(qtbot, session)
    panel = page.postings
    assert not panel.opened and panel.table.isHidden()  # closed until asked
    pay_alfa(page)
    before = counts(session.conn)
    panel.flip()  # F7
    assert panel.opened and prefs().flag(OPEN_KEY, False)
    assert shown(panel) == [("60.1", "ALFA MMC, Договор 1", "51", "Kapital AZN", 118000)]
    assert panel.summary.text() == "1  ·  1 180.00"
    assert counts(session.conn) == before  # nothing written
    assert page.doc is None and page.dirty

    type_text(page.line_rows[0].amount, "1000")  # typing on: asked again after a pause
    qtbot.waitUntil(lambda: [r.amount for r in panel.model.rows] == [100000])
    assert counts(session.conn) == before


def test_a_posted_one_shows_its_postings(qtbot, session):
    prefs().set(OPEN_KEY, True)  # left open: it stays open
    page = new_page(qtbot, session)
    pay_alfa(page)
    assert page.save(post=True)
    panel = page.postings
    panel.refresh()
    assert shown(panel) == [("60.1", "ALFA MMC, Договор 1", "51", "Kapital AZN", 118000)]
    assert panel.model.rows[0].invoice == "MT001"


def test_what_would_not_post_says_why(qtbot, session):
    page = new_page(qtbot, session)
    page.postings.flip()  # nothing typed yet: no counterparty, no amount
    assert page.postings.preview.error
    assert page.postings.error.isVisibleTo(page) and page.postings.table.isHidden()
    assert page.postings.summary.text() == "не проведётся"


def press_f7(widget) -> None:
    [shortcut] = [s for s in widget.findChildren(QShortcut) if s.key() == QKeySequence("F7")]
    shortcut.activated.emit()


def test_f7_on_a_journal_row_shows_its_postings(qtbot, session):
    page = new_page(qtbot, session)
    pay_alfa(page)
    assert page.save(post=True) and page.doc is not None
    journal = JournalPage(session)
    qtbot.addWidget(journal)
    journal.show()
    qtbot.waitExposed(journal)
    assert journal._current_id() == page.doc.document_id  # the newest chosen
    press_f7(journal.table)
    [peek] = journal.table.findChildren(PostingsPeek)
    assert shown(peek) == [("60.1", "ALFA MMC, Договор 1", "51", "Kapital AZN", 118000)]
    peek.close()


def test_a_right_click_on_a_row_offers_its_postings(qtbot, session, monkeypatch):
    """Who does not know F7 finds it in the menu of a row: «Проводки  F7» shows them."""
    from PySide6.QtWidgets import QMenu

    page = new_page(qtbot, session)
    pay_alfa(page)
    assert page.save(post=True)
    journal = JournalPage(session)
    qtbot.addWidget(journal)
    journal.show()
    qtbot.waitExposed(journal)
    offered: list[str] = []

    class Menu(QMenu):
        def exec(self, *_):  # type: ignore[override]
            offered.extend(a.text() for a in self.actions())
            self.actions()[0].trigger()

    monkeypatch.setattr("modern_gl.desktop.posting_peek.QMenu", Menu)
    table = journal.table
    table.customContextMenuRequested.emit(table.visualRect(table.currentIndex()).center())
    assert offered == ["Проводки  F7"]
    [peek] = table.findChildren(PostingsPeek)
    assert shown(peek) == [("60.1", "ALFA MMC, Договор 1", "51", "Kapital AZN", 118000)]
    peek.close()


def test_nothing_of_the_books_in_only_the_warehouse(qtbot, session):
    session.ledger.set_company_mode(session.company_id, STOCK_ONLY)
    page = new_page(qtbot, session)
    assert page.postings.isHidden()
    page.postings.flip()
    assert not page.postings.opened
