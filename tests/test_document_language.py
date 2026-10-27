"""The language of the texts the program writes into a company's documents (D152): a
setting of the company, not of the interface. Switching the interface leaves the texts and
the documents as they are; a rebuild finds nothing to change."""

from __future__ import annotations

import sqlite3

import pytest

from modern_gl.application.document_language import resolve, stored
from modern_gl.application.ledger import Ledger
from modern_gl.application.rebuild import module_rebuilders
from modern_gl.application.workspace import Workspace
from modern_gl.demo_year import create_year_demo
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import document_language, set_document_language, set_language, trd
from modern_gl.infrastructure.db import close, connect

AUTO_TEXTS = "SELECT memo FROM postings UNION ALL SELECT memo FROM documents"


def texts(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(AUTO_TEXTS)]


def test_document_texts_follow_the_company_not_the_interface():
    set_language("ru")
    set_document_language("az")
    assert trd("Комиссия банка") == "Bank komissiyası"
    set_document_language(None)  # not chosen: the interface's, as before
    assert trd("Комиссия банка") == "Комиссия банка"
    assert document_language() == "ru"


def test_the_interface_switched_rewrites_nothing():
    """The mistake found by D148's test: a rebuild in the other interface language found
    every module document «changed» (only its texts) and reposted 972 of them."""
    set_language("ru")  # a Russian interface, Azerbaijani documents
    set_document_language("az")
    conn = connect(":memory:")
    ledger = Ledger(conn)
    company_id = create_year_demo(ledger)
    assert "Bank komissiyası" in texts(conn)
    assert "Комиссия банка" not in texts(conn)
    ledger.set_closed_through(company_id, None)
    set_language("az")
    for name, module in module_rebuilders(ledger).items():
        assert module.rebuild_postings(company_id, "2026-01-01") == [], name
    close(conn)


def test_a_new_company_writes_in_azerbaijani(tmp_path):
    set_language("ru")
    ws = Workspace(tmp_path)
    path = ws.create("Firma", chart=None)
    conn, company_id = ws.open(path)
    assert stored(conn, company_id) == "az"
    assert document_language() == "az"
    close(conn)


def test_the_setting_is_kept_and_audited(ledger):
    company_id = ledger.create_company("Firma")
    ledger.set_document_language(company_id, "ru")
    assert stored(ledger.conn, company_id) == "ru"
    audited = ledger.conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'set_document_language'"
    ).fetchone()[0]
    assert audited == 1
    with pytest.raises(ValidationError):
        ledger.set_document_language(company_id, "en")


@pytest.mark.parametrize("written, interface, found", [("az", "ru", "az"), ("ru", "az", "ru")])
def test_an_older_file_keeps_the_language_its_texts_are_in(tmp_path, written, interface, found):
    """A file of an older program has no setting: its texts tell which language they were
    written in, whatever the interface is now."""
    set_language(written)
    path = tmp_path / "Old.gl"
    conn = connect(path)
    create_year_demo(Ledger(conn))
    conn.execute("UPDATE companies SET document_language = NULL")
    close(conn)
    set_language(interface)
    ws = Workspace(tmp_path)
    viewed, company_id = ws.view(path)  # viewing writes nothing, but writes in that language
    assert stored(viewed, company_id) is None
    assert document_language() == found
    close(viewed)
    conn, company_id = ws.open(path)
    assert stored(conn, company_id) == found  # chosen once, for good
    close(conn)


def test_without_texts_the_interface_decides(ledger):
    set_language("ru")
    company_id = ledger.create_company("Firma")
    assert stored(ledger.conn, company_id) is None
    assert resolve(ledger.conn, company_id) == "ru"


def test_the_company_menu_chooses_the_language(qtbot, tmp_path):
    from modern_gl.desktop.main_window import MainWindow

    ws = Workspace(tmp_path)
    path = ws.create("Firma", chart=None)
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.open_company(path)
    assert win.session is not None
    win.set_document_language("ru")
    assert stored(win.session.conn, win.session.company_id) == "ru"
    assert trd("Комиссия банка") == "Комиссия банка"
    win.shutdown()
