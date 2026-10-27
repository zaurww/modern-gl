"""Who entered and posted a document, in the window (D82)."""

import pytest
from PySide6.QtCore import QSettings

from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import list_documents
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.journal_page import AUTHOR, JournalPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure.db import connect


@pytest.fixture
def window(qtbot, tmp_path):
    ws = Workspace(tmp_path / "data")
    conn = connect(ws.new_path("ДЕМО ООО"))
    create_demo_company(Ledger(conn, actor="Aynur"))
    conn.close()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(ws, settings)
    qtbot.addWidget(win)
    win.start()
    win.show()
    yield win
    win.shutdown()


def journal(win) -> JournalPage:
    win.show_place(("journal",))
    page = win.stack.currentWidget()
    assert isinstance(page, JournalPage)
    return page


def test_the_document_says_who_posted_it(window):
    s = window.open_session
    doc = next(d for d in list_documents(s.conn, s.company_id) if d.status == "posted")
    window.show_document(doc.id)
    page = window.stack.currentWidget()
    assert isinstance(page, DocumentPage)
    assert page.authors.isVisibleTo(page)
    assert page.authors.text().startswith("Провёл Aynur · ")


def test_a_new_document_says_nothing_yet(window):
    window.new_document()
    page = window.stack.currentWidget()
    assert isinstance(page, DocumentPage)
    assert not page.authors.isVisibleTo(page)


def test_the_name_set_in_the_program_signs_what_is_posted(window):
    assert journal(window).table.isColumnHidden(AUTHOR)  # one person: no column

    window.set_user_name("Zaur")

    assert window.user_name() == "Zaur"
    s = window.open_session
    assert s.ledger.actor == "Zaur"
    draft = next(d for d in list_documents(s.conn, s.company_id) if d.status == "draft")
    s.ledger.post(s.company_id, draft.id)
    page = journal(window)
    page.refresh()
    assert not page.table.isColumnHidden(AUTHOR)  # two people now
    assert page.model.authors[draft.id] == "Zaur"
