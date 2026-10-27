"""Сравнение книг (D98): the common, IFRS and tax books side by side; a difference is the
adjustment layer itself. Figures of the golden example (conftest), worked out by hand."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.reports_page import BooksPage, OsvPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import to_qdate
from modern_gl.reporting.books import compare_books
from tests.helpers.qt import running_app


def adjust(demo) -> None:
    led, cid = demo.ledger, demo.company_id
    # IFRS: 50.00 more of materials written off; tax: the write-off of 300.00 not accepted
    led.post_new(cid, "2026-02-25", [demo.p("721", "201", "50.00")], "МСФО", "ifrs_adj")
    led.post_new(cid, "2026-02-26", [demo.p("201", "721", "300.00")], "Налог", "tax_adj")


def figures(rows) -> dict[str, tuple[int, int, int]]:
    return {r.code: (r.common, r.ifrs, r.tax) for r in rows}


def test_each_book_is_the_common_one_plus_its_adjustments(demo):
    adjust(demo)
    rows = compare_books(demo.ledger.conn, demo.company_id, "2026-02-28")
    assert figures(rows) == {
        "201": (140_000, 135_000, 170_000),  # 1 400 Dt; IFRS −50; tax +300
        "22": (900_000, 900_000, 900_000),  # the group: 7 000 + 2 000
        "221": (700_000, 700_000, 700_000),
        "222": (200_000, 200_000, 200_000),
        "301": (-1_000_000, -1_000_000, -1_000_000),  # 10 000 Kt
        "531": (-70_000, -70_000, -70_000),  # 700 Kt
        "721": (30_000, 35_000, 0),
    }
    assert sum(r.ifrs for r in rows if r.depth == 0) == 0  # each book still balances
    assert sum(r.tax for r in rows if r.depth == 0) == 0


def test_only_the_differences_and_the_day(demo):
    adjust(demo)
    cid, conn = demo.company_id, demo.ledger.conn
    differ = compare_books(conn, cid, "2026-02-28", only_differences=True)
    assert [(r.code, r.ifrs_adj, r.tax_adj) for r in differ] == [
        ("201", -5_000, 30_000),
        ("721", 5_000, -30_000),
    ]
    # before the adjustments the books agree
    assert compare_books(conn, cid, "2026-02-24", only_differences=True) == []
    # the IFRS adjustment is there, the tax one is not yet
    assert [(r.code, r.tax_adj) for r in compare_books(conn, cid, "2026-02-25", True)] == [
        ("201", 0),
        ("721", 0),
    ]


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, make_demo):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(running_app())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    assert win.session is not None
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def compare_buttons(page) -> list:
    """«Сравнить книги» in «⋯» of the ОСВ (D127): what it does, when it is there."""
    return [
        fn for item in page.more_items() if item for text, fn in [item] if text == "Сравнить книги"
    ]


def test_without_parallel_books_there_is_nothing_to_compare(demo, qtbot):
    cid = demo.company_id
    session = Session(
        demo.ledger.conn, demo.ledger, cid, "ООО Тест", Catalog(demo.ledger.conn, cid)
    )
    osv = OsvPage(session)
    qtbot.addWidget(osv)
    assert compare_buttons(osv) == []


def test_the_osv_opens_the_comparison(window, qtbot):
    # the demo keeps parallel books: on 28.02 IFRS writes 50.00 of stock down (Dt 26 / Ct 10)
    palette = window.command_palette()
    assert palette is not None
    palette.search.setText("Сравнение")
    assert "Сравнение книг" in [e.title for e in palette.entries_shown()]
    palette.close()
    window.show_place(("osv",))
    osv = window.stack.currentWidget()
    assert isinstance(osv, OsvPage)
    compare_buttons(osv)[0]()
    page = window.stack.currentWidget()
    assert isinstance(page, BooksPage)
    qtbot.waitUntil(lambda: bool(page.model.rows))
    assert [(r.code, r.ifrs_adj, r.tax_adj) for r in page.model.rows] == [
        ("10", -5_000, 0),
        ("26", 5_000, 0),
    ]
    assert page.footer.text() == "Расхождения по счетам: 2"
    page.day.setDate(to_qdate(date(2026, 2, 27)))  # a new day is shown at once (D105)
    qtbot.waitUntil(lambda: not page.model.rows)
    assert page.footer.text() == "Книги совпадают  ✓"
    page.only.setChecked(False)  # every account with a balance
    assert len(page.model.rows) > 2
