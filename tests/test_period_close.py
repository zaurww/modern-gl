"""«Закрытие периода» (D95): the window over `Ledger.set_closed_through` — the usual ends
of a period, drafts that could not be posted afterwards, opening a part or all again."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.ledger import Ledger
from modern_gl.application.period import closed_through, drafts_through, period_ends
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.period_dialog import PeriodDialog
from modern_gl.desktop.widgets import to_qdate
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import connect

pytestmark = pytest.mark.questions("Yes")  # deleting, posting: yes


def ends(working: date) -> list[tuple[str, date]]:
    return [(e.title, e.day) for e in period_ends(working)]


def test_period_ends_are_last_month_quarter_and_year():
    assert ends(date(2026, 5, 15)) == [
        ("Конец прошлого месяца", date(2026, 4, 30)),
        ("Конец прошлого квартала", date(2026, 3, 31)),
        ("Конец прошлого года", date(2025, 12, 31)),
    ]
    # April: the last month is the last quarter — offered once
    assert ends(date(2026, 4, 2)) == [
        ("Конец прошлого месяца", date(2026, 3, 31)),
        ("Конец прошлого года", date(2025, 12, 31)),
    ]
    assert ends(date(2026, 1, 10)) == [("Конец прошлого месяца", date(2025, 12, 31))]


def test_drafts_through_counts_the_drafts_up_to_the_day(demo):
    led, cid = demo.ledger, demo.company_id
    led.create_draft(cid, "2026-01-20", [demo.p("721", "201", "10.00")])
    led.create_draft(cid, "2026-02-10", [demo.p("721", "201", "20.00")])
    assert drafts_through(led.conn, cid, "2026-01-19") == 0
    assert drafts_through(led.conn, cid, "2026-01-31") == 1
    assert drafts_through(led.conn, cid, date(2026, 2, 28)) == 2


@pytest.fixture
def window(qtbot, tmp_path):
    conn = connect(tmp_path / "ДЕМО ООО.gl")
    create_demo_company(Ledger(conn))
    conn.close()
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def audit(s) -> list[str]:
    return [
        r["details"]
        for r in s.conn.execute(
            "SELECT details FROM audit_events WHERE company_id = ? "
            "AND action = 'set_closed_through' ORDER BY id",
            (s.company_id,),
        )
    ]


def test_dialog_closes_through_the_last_month_and_warns_of_drafts(window, qtbot):
    s = window.session
    s.ledger.create_draft(s.company_id, "2026-01-25", [], "черновик января")
    dialog = PeriodDialog(s, window)
    qtbot.addWidget(dialog)
    assert dialog.day() == "2026-01-31"  # the end of the month before the working date
    assert dialog.warning.isVisibleTo(dialog)
    assert "Черновиков по 31.01.2026: 1" in dialog.warning.text()
    assert not dialog.reopen.isVisibleTo(dialog)  # nothing is closed yet
    dialog.ok.click()
    assert closed_through(s.conn, s.company_id) == "2026-01-31"
    assert audit(s) == ['{"from": null, "to": "2026-01-31"}']
    # the books refuse what is now closed
    with pytest.raises(LedgerError, match=r"период закрыт по 31\.01\.2026"):
        s.ledger.post(s.company_id, s.ledger.create_draft(s.company_id, "2026-01-26", []))


def test_an_earlier_day_opens_part_of_the_period_and_all_can_be_opened(window, qtbot):
    s = window.session
    s.ledger.set_closed_through(s.company_id, "2026-01-31")
    dialog = PeriodDialog(s, window)
    qtbot.addWidget(dialog)
    assert dialog.day() == "2026-01-31"  # starts on what is closed
    assert not dialog.ok.isEnabled()  # the same day changes nothing
    dialog.through.setDate(to_qdate(date(2026, 1, 15)))
    assert dialog.ok.text() == "Открыть часть периода"
    assert "Период с 16.01.2026 по 31.01.2026 снова станет открытым." in dialog.warning.text()
    dialog.ok.click()
    assert closed_through(s.conn, s.company_id) == "2026-01-15"
    again = PeriodDialog(s, window)
    qtbot.addWidget(again)
    assert again.reopen.isVisibleTo(again)
    again.reopen.click()
    assert closed_through(s.conn, s.company_id) is None
    assert audit(s)[-1] == '{"from": "2026-01-15", "to": null}'


def test_ctrl_k_offers_closing_the_period(window):
    p = window.command_palette()
    assert p is not None
    commands = [e.title for e in p.entries_shown() if e.group == "Команды"]
    assert "Закрытие периода…" in commands


def test_require_open_names_the_last_closed_day(ledger):
    """One check of the closed period for the ledger, the warehouse and accruals: the
    last closed day as the user reads it goes into the text of the caller."""
    from modern_gl.application.common import company_row, require_open
    from modern_gl.domain.errors import PeriodClosedError

    cid = ledger.create_company("Период")
    ledger.set_closed_through(cid, "2026-01-31")
    company = company_row(ledger.conn, cid)
    require_open(company, "2026-02-01", lambda closed: "не нужен")
    with pytest.raises(PeriodClosedError, match=r"^31\.01\.2026 — закрыт$"):
        require_open(company, "2026-01-31", lambda closed: f"{closed} — закрыт")
    ledger.set_closed_through(cid, None)
    require_open(company_row(ledger.conn, cid), "2020-01-01", lambda closed: "не нужен")
