"""A large company's reports are read in a worker on its own connection (debt 6): the
window gets the same figures, later; a small one reads at once."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.ledger import Ledger
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.home_page import HomePage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.reports_page import OsvPage
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace


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
    win.session.background.wait()
    win.shutdown()


def test_a_small_company_reads_at_once(window):
    assert not window.session.large  # 25 postings
    window.show_place(("osv",))
    assert window.stack.currentWidget().model.rows  # no waiting


def test_a_large_company_reads_in_the_background_with_the_same_figures(window, qtbot):
    window.show_place(("osv",))
    osv = window.stack.currentWidget()
    assert isinstance(osv, OsvPage)
    at_once = [(r.code, r.closing_dt, r.closing_ct) for r in osv.model.rows if hasattr(r, "code")]
    window.session.large = True  # as with 20 000 postings and more
    osv.model.set(osv.model.columns, [])
    osv.refresh()
    qtbot.waitUntil(lambda: bool(osv.model.rows))
    later = [(r.code, r.closing_dt, r.closing_ct) for r in osv.model.rows if hasattr(r, "code")]
    assert later == at_once

    window.show_place(("home",))
    home = window.stack.currentWidget()
    assert isinstance(home, HomePage)
    qtbot.waitUntil(lambda: len(home.sections) == 4)  # with the backup (D97)
    money = [ln.figure.text() for ln in home.sections[1].lines]
    qtbot.waitUntil(
        lambda: [ln.figure.text() for ln in home.sections[1].lines] == ["1 750.00", "7 580.00"]
    )
    assert money


def test_the_last_refresh_wins_and_a_closed_page_gets_nothing(window, qtbot):
    window.session.large = True
    window.show_place(("osv",))
    osv = window.stack.currentWidget()
    shown: list = []
    osv.present = lambda data: shown.append(data)  # type: ignore[method-assign]
    osv.refresh()
    osv.refresh()
    window.session.background.wait()
    qtbot.waitUntil(lambda: len(shown) == 1)
    qtbot.wait(50)
    assert len(shown) == 1  # the first run's result was dropped
