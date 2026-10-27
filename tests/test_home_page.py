"""«Bu gün» (D86): what waits, the money, the rates — figures of the demo company counted
by hand from its trial balance (ОСВ February 2026)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt

import modern_gl.desktop.main_window  # noqa: F401  modules add their rows of «what waits»
from modern_gl.application.attention import POST_DRAFTS
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import load_document
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.home_page import HomePage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.overview import attention, money, rates
from modern_gl.reporting.reports import trial_balance
from tests.helpers.qt import layout_widget, running_app


@pytest.fixture
def ledger():
    conn = connect(":memory:")
    led = Ledger(conn)
    create_demo_company(led)
    return led


def cid(led: Ledger) -> int:
    return led.conn.execute("SELECT id FROM companies").fetchone()["id"]


def test_what_waits_on_the_day(ledger):
    c = cid(ledger)
    rows = {r.text: r for r in attention(ledger.conn, c, "2026-02-28")}
    drafts = rows["Черновики в журнале"]
    assert (drafts.count, drafts.place, drafts.action) == (1, ("journal",), POST_DRAFTS)
    # MT2601001842: 1 200.00 + ƏDV 216.00, nothing paid on its number
    unpaid = rows["Неоплаченные e-qaimə поставщиков"]
    assert (unpaid.count, unpaid.amount) == (1, 141600)
    # the draft «Аренда за март» is dated 28.02: on the 27th nothing waits in the journal
    assert "Черновики в журнале" not in {r.text for r in attention(ledger.conn, c, "2026-02-27")}


def test_money_is_the_cash_and_bank_balances(ledger):
    c = cid(ledger)
    shown = {(m.account_code, m.name): m.balance for m in money(ledger.conn, c, "2026-02-28")}
    # ОСВ 28.02: 50 — 1 750.00 Dt; 51 — 7 580.00 Dt (9 000 + 1 180 − 2 600)
    assert shown == {("50", "Касса"): 175000, ("51", "Основной расчётный счёт"): 758000}
    # 31.01: 51 — 9 000.00, 50 — nothing moved yet
    january = {m.account_code: m.balance for m in money(ledger.conn, c, "2026-01-31")}
    assert january == {"51": 900000}


def test_rates_offer_usd_and_eur_first(ledger):
    c = cid(ledger)
    shown = rates(ledger.conn, c, "2026-02-28")
    assert [r.code for r in shown][:2] == ["USD", "EUR"]
    assert all(r.rate is None and not r.of_the_day for r in shown)


def test_post_drafts_posts_and_leaves_what_cannot_post(ledger):
    c = cid(ledger)
    acc = ledger.account_id
    bad = ledger.create_draft(  # 26 needs its cost item: this one cannot post
        c, "2026-02-20", [PostingInput(acc(c, "26"), acc(c, "50"), "10")], "Без статьи"
    )
    posted, left = ledger.post_drafts(c, "2026-02-28")
    assert len(posted) == 1 and [n for n, _ in left] == [load_document(ledger.conn, c, bad).number]
    assert load_document(ledger.conn, c, bad).status == "draft"
    osv = {r.code: r for r in trial_balance(ledger.conn, c, "2026-02-01", "2026-02-28").rows}
    assert osv["26"].turnover_dt == 55000 + 40000  # + the rent of March, 400.00
    rows = {r.text: r for r in attention(ledger.conn, c, "2026-02-28")}
    assert rows["Черновики в журнале"].count == 1  # the one left
    assert rows["Неоплаченные e-qaimə поставщиков"].amount == 141600 + 40000


@pytest.fixture
def window(qtbot, tmp_path, make_demo):
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


def home(window) -> HomePage:
    window.show_place(("home",))
    page = window.stack.currentWidget()
    assert isinstance(page, HomePage)
    return page


def test_home_opens_first_and_shows_the_three_lists(window):
    assert isinstance(window.stack.currentWidget(), HomePage)
    page = home(window)
    texts = [[ln.text.text() for ln in s.lines] for s in page.sections]
    assert texts[0] == ["Черновики в журнале", "Неоплаченные e-qaimə поставщиков"]
    assert texts[1] == ["Касса", "Основной расчётный счёт"]
    assert [ln.figure.text() for ln in page.sections[1].lines] == ["1 750.00", "7 580.00"]
    assert texts[2][:2] == ["USD", "EUR"]


def test_refresh_leaves_no_old_lists_on_the_page(window, qtbot):
    page = home(window)
    old = list(page.sections)
    page.refresh()
    assert all(s.isHidden() for s in old)  # at once, not when Qt deletes them
    assert len(page.sections) == 4 and not set(page.sections) & set(old)
    qtbot.waitUntil(lambda: all(s.isVisible() for s in page.sections))


def test_a_line_opens_its_place(window, qtbot):
    page = home(window)
    qtbot.mouseClick(page.sections[0].lines[0], Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget().title() == "Журнал"


def test_post_all_then_undo(window):
    page = home(window)
    page.post_drafts()
    s = window.session
    assert window.toast.message() == "Проведено документов: 1"
    assert [ln.text.text() for ln in home(window).sections[0].lines] == [
        "Неоплаченные e-qaimə поставщиков"
    ]
    window.toast.undo_button.click()
    drafts = s.conn.execute("SELECT COUNT(*) FROM documents WHERE status = 'draft'").fetchone()
    assert drafts[0] == 1
    assert home(window).sections[0].lines[0].text.text() == "Черновики в журнале"


def test_viewing_and_stock_only(window):
    window.session.read_only = True
    page = home(window)
    page.refresh()
    post = layout_widget(page.sections[0].lines[0].buttons, 0)
    assert post.isHidden()
    window.session.read_only = False
    window.set_stock_only(True)
    page = home(window)
    # what waits, the rates and the backup (D97): no books, no money list
    assert len(page.sections) == 3
