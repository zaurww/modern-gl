"""Why the posted books were taken back (D96): the reason told when a document is unposted
or deleted, or a closed period opened again, goes to the audit trail; a document's
«История изменений» shows who, when, what and why."""

from __future__ import annotations

import json
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.history import document_history
from modern_gl.application.period import closed_through
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.history_dialog import HistoryDialog
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.period_dialog import PeriodDialog
from modern_gl.desktop.widgets import to_qdate
from tests.conftest import REASON


def last_event(conn, action: str) -> dict:
    row = conn.execute(
        "SELECT details FROM audit_events WHERE action = ? ORDER BY id DESC LIMIT 1", (action,)
    ).fetchone()
    return json.loads(row[0])


def test_ledger_keeps_the_reason_with_the_change(demo):
    led, cid = demo.ledger, demo.company_id
    first, second = demo.docs[0], demo.docs[1]
    led.unpost(cid, first, "  неверная сумма ")
    assert last_event(led.conn, "unpost")["reason"] == "неверная сумма"  # trimmed
    assert last_event(led.conn, "unpost")["number"] == 1  # the copy is still there
    led.delete_document(cid, second, "дубль")
    assert last_event(led.conn, "delete")["reason"] == "дубль"
    led.set_closed_through(cid, "2026-01-31")
    led.set_closed_through(cid, None, "сдаём уточнённую декларацию")
    assert last_event(led.conn, "set_closed_through") == {
        "from": "2026-01-31",
        "to": None,
        "reason": "сдаём уточнённую декларацию",
    }
    # no reason told: nothing is added
    led.post(cid, first)
    led.unpost(cid, first)
    assert "reason" not in last_event(led.conn, "unpost")


def test_document_history_reads_the_trail(demo):
    led, cid = demo.ledger, demo.company_id
    draft = led.create_draft(cid, "2026-02-25", [demo.p("721", "201", "10.00")], "Списание")
    led.post(cid, draft)
    led.unpost(cid, draft, "не тот счёт")
    events = document_history(led.conn, cid, draft)
    assert [(e.action, e.reason) for e in events] == [
        ("Создан черновик", ""),
        ("Проведён", ""),
        ("Проведение отменено", "не тот счёт"),
    ]
    assert {e.actor for e in events} == {led.actor}
    assert document_history(led.conn, cid + 1, draft) == []  # another company's


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, make_demo):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def opened(window, doc_id: int):
    window.open_document(doc_id)
    return window.stack.currentWidget()


def test_unpost_on_the_page_asks_why_and_can_be_cancelled(window):
    s = window.session
    window.show_place(("journal",))
    doc = window.pages[("journal",)].model.docs[0]
    page = opened(window, doc.id)
    REASON["text"] = None  # changed their mind
    page.unpost()
    assert page.status.text() == "Проведён"
    REASON["text"] = "ошибка в дате"
    page.unpost()
    assert page.status.text() == "Черновик"
    events = document_history(s.conn, s.company_id, doc.id)
    assert (events[-1].action, events[-1].reason) == ("Проведение отменено", "ошибка в дате")
    assert "История изменений" in [item[0] for item in page.menu_items() if item]


def test_deleting_a_posted_document_from_the_journal_keeps_the_reason(window):
    s = window.session
    window.show_place(("journal",))
    journal = window.pages[("journal",)]
    journal.table.selectRow(0)
    doc_id = journal._current_id()
    assert doc_id is not None
    REASON["text"] = "введён дважды"
    journal._delete_current()
    assert doc_id not in [d.id for d in journal.model.docs]
    assert last_event(s.conn, "delete")["reason"] == "введён дважды"


def test_opening_a_closed_period_asks_why(window, qtbot):
    s = window.session
    s.ledger.set_closed_through(s.company_id, "2026-01-31")
    dialog = PeriodDialog(s, window)
    qtbot.addWidget(dialog)
    dialog.through.setDate(to_qdate(date(2026, 1, 15)))
    REASON["text"] = None
    dialog.ok.click()
    assert closed_through(s.conn, s.company_id) == "2026-01-31"  # not opened
    REASON["text"] = "акт сверки"
    dialog.ok.click()
    assert closed_through(s.conn, s.company_id) == "2026-01-15"
    assert last_event(s.conn, "set_closed_through")["reason"] == "акт сверки"


def test_history_dialog_shows_each_event_with_its_reason(demo, qtbot):
    led, cid = demo.ledger, demo.company_id
    led.unpost(cid, demo.docs[0], "неверная сумма")
    dialog = HistoryDialog("Документ №1", document_history(led.conn, cid, demo.docs[0]))
    qtbot.addWidget(dialog)
    texts = [label.text() for label in dialog.lines]
    assert "Проведение отменено" in texts[-1]
    assert texts[-1].endswith("Причина: неверная сумма")


def test_every_history_action_has_azerbaijani_translation():
    from modern_gl.application.history import ACTIONS
    from modern_gl.i18n_az import AZ

    assert [text for text in ACTIONS.values() if text not in AZ] == []
