"""«Журнал действий» (D178): the company's events from the audit trail with
the sessions — the company opened and closed, on which computer; who, what, to what, why;
newest first; a document's event opens it. A snapshot viewed writes nothing, and a session
is no change for the backup made on closing."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.action_log import LogFilter, action_log, log_actors
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.reports_page import ActionLogPage
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.db import connect
from tests.helpers.qt import running_app

TODAY = date.today()


def today(cid: int, actor: str = "") -> LogFilter:
    return LogFilter(cid, TODAY - timedelta(days=1), TODAY + timedelta(days=1), actor)


def test_events_are_read_newest_first_with_what_and_why(ledger: Ledger, conn):
    """A document entered, posted, unposted with a reason and deleted: four events, the
    newest first; each says what was done to «Документ №1»; the deleted one too — its
    number from what the event kept; the reason of the unposting is there. The document
    opens while it exists."""
    cid = ledger.create_company("Firma")
    ledger.add_account(cid, "26", "Расходы", account_class="expense")
    ledger.add_account(cid, "60", "Поставщики", account_class="liability")
    lines = [PostingInput(ledger.account_id(cid, "26"), ledger.account_id(cid, "60"), "10")]
    doc = ledger.create_draft(cid, "2026-03-05", lines, "Аренда")
    ledger.post(cid, doc)
    assert action_log(conn, today(cid))[0].document_id == doc
    ledger.unpost(cid, doc, reason="не та сумма")
    ledger.delete_document(cid, doc)

    events = [e for e in action_log(conn, today(cid)) if e.kind == "Документ"]
    assert [e.action for e in events] == [
        "Удаление",
        "Отмена проведения",
        "Проведение",
        "Черновик",
    ]
    assert {e.subject for e in events} == {"№1"}
    assert events[1].reason == "не та сумма"
    assert all(e.document_id is None for e in events)  # deleted: nothing to open
    assert action_log(conn, today(cid))[-1].kind == "Компания"  # created first


def test_a_session_names_the_computer_and_filters_by_person(conn):
    """The company opened and closed by two people: «Открытие» / «Закрытие» with the
    computer; «Кто» keeps one person's; a period before today has none."""
    aynur, murad = Ledger(conn, actor="Aynur"), Ledger(conn, actor="Murad")
    cid = aynur.create_company("Firma")
    aynur.log_session(cid, "open")
    murad.log_session(cid, "open")
    murad.log_session(cid, "close")
    with pytest.raises(ValidationError):
        murad.log_session(cid, "sleep")

    murads = action_log(conn, today(cid, "Murad"))
    assert [(e.action, e.kind) for e in murads] == [
        ("Закрытие", "Компания"),
        ("Открытие", "Компания"),
    ]
    assert all(" · " in e.computer for e in murads)  # computer · its user
    assert log_actors(conn, cid) == ["Aynur", "Murad"]
    yesterday = LogFilter(cid, TODAY - timedelta(days=3), TODAY - timedelta(days=2))
    assert action_log(conn, yesterday) == []


def test_a_session_is_no_change_for_the_backup(tmp_path, ledger: Ledger, conn):
    """Opening and closing a company do not make a backup on closing."""
    cid = ledger.create_company("Firma")
    backup.make_backup(conn, tmp_path, "Firma")
    ledger.log_session(cid, "open")
    ledger.log_session(cid, "close")
    assert not backup.changed_since_last(conn, tmp_path)
    ledger.rename_company(cid, "Firma 2")
    assert backup.changed_since_last(conn, tmp_path)


@pytest.fixture
def company(tmp_path, make_demo):
    path = make_demo(tmp_path / "ДЕМО ООО.gl")
    return Workspace(tmp_path), path


def sessions(path) -> list[str]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT action FROM audit_events WHERE entity = 'session' ORDER BY id")
        return [r["action"] for r in rows]
    finally:
        conn.close()


def test_the_window_writes_opening_and_closing_but_not_viewing(qtbot, company):
    ws, path = company
    theme.apply(running_app())
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)  # a snapshot: nothing written
    win.shutdown()
    assert sessions(path) == []
    for _ in range(2):
        win = MainWindow(ws)
        qtbot.addWidget(win)
        win.open_company(path)
        win.shutdown()
    assert sessions(path) == ["open", "close", "open", "close"]
    assert len(ws.backups(path)) == 1  # the first closing; then no change, no new backup


def test_the_page_lists_the_events_and_opens_a_document(qtbot, demo_window):
    """From «Все отчёты»: the opening of this session on top with its computer; «Кто»
    lists the names; a document's event opens the document."""
    win = demo_window
    win.reports.open_catalog_report("action_log")
    page = win.stack.currentWidget()
    assert isinstance(page, ActionLogPage)
    page.period.set_period(TODAY - timedelta(days=1), TODAY)
    page.refresh()
    qtbot.waitUntil(lambda: bool(page.model.rows))
    top = page.model.rows[0]
    assert (top.action, top.kind) == ("Открытие", "Компания") and top.computer
    headers = [page.model.headerData(i, Qt.Orientation.Horizontal) for i in range(6)]
    assert headers[:5] == ["Когда", "Кто", "Что", "Объект", "Причина"]
    assert page.actor.count() >= 2  # «Все» and the names

    opened: list[int] = []
    page.open_document.connect(opened.append)
    doc = next(e for e in page.model.rows if e.document_id is not None)
    page.drill(doc)
    assert opened == [doc.document_id]
