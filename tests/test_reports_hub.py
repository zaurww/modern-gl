"""«Все отчёты» (D114): every report on one page by group, the search, the pinned ones
in the sidebar (kept in QSettings), Ctrl+K, a warehouse-only company and viewing."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.main_window import report_places as places
from modern_gl.desktop.reports_hub import HUB, AccountPrompt, ReportsPage, catalog
from modern_gl.desktop.reports_page import StatementsPage
from modern_gl.desktop.reports_page.account import CardPage
from modern_gl.infrastructure.db import connect


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    )


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


def hub(window) -> ReportsPage:
    window.show_place(HUB)
    page = window.stack.currentWidget()
    assert isinstance(page, ReportsPage)
    return page


def tile(page: ReportsPage, report_id: str):
    return next(t for t in page.tiles if t.report.id == report_id)


def type_text(edit, text: str) -> None:
    edit.setText(text)
    edit.textEdited.emit(text)


def sidebar_keys(window) -> list:
    nav = window.sidebar.nav
    return [nav.item(i).data(Qt.ItemDataRole.UserRole) for i in range(nav.count())]


def test_the_page_shows_every_group(window):
    page = hub(window)
    shown = {t.report.group for t in page.tiles}
    assert shown == set(catalog.GROUPS)
    assert [t.report.id for t in page.tiles[:3]] == ["balance", "profit", "cash"]
    assert {
        "osv",
        "subconto",
        "card",
        "analysis",
        "subconto_analysis",
        "invoices",
        "landed",
        "stock",
    } <= {t.report.id for t in page.tiles}
    assert page.title() == "Отчёты"


def test_the_sidebar_has_one_place_and_the_reports_pinned_by_default(window):
    keys = sidebar_keys(window)
    at = keys.index(HUB)
    # what the sidebar had before: ОСВ, the balance and the profit — right under it
    assert keys[at + 1 : at + 4] == [("osv",), ("statements", "balance"), ("statements", "profit")]
    assert ("invoices",) not in keys  # in the catalog; Ctrl+8 still opens it
    window.show_place(("invoices",))
    assert window.sidebar.nav.currentItem() is window.sidebar.item_for(HUB)


def test_the_profit_and_loss_opens_the_statements_on_its_view(window, qtbot):
    page = hub(window)
    qtbot.mouseClick(tile(page, "profit"), Qt.MouseButton.LeftButton)
    statements = window.stack.currentWidget()
    assert isinstance(statements, StatementsPage)
    assert statements.view == "profit"
    qtbot.waitUntil(lambda: bool(statements.model.rows))
    assert statements.model.rows[-1].title == "Чистая прибыль (убыток)"
    item = window.sidebar.item_for(("statements", "profit"))
    assert window.sidebar.nav.currentItem() is item
    # the same page, another view: from the pinned «Баланс»
    window.sidebar.nav.setCurrentItem(window.sidebar.item_for(("statements", "balance")))
    assert window.stack.currentWidget() is statements
    assert statements.view == "balance"
    assert catalog.recent()[:2] == ["balance", "profit"]  # remembered as opened


def test_pinning_changes_the_sidebar_and_is_remembered(window, qtbot):
    page = hub(window)
    cash = tile(page, "cash")
    assert not cash.pinned
    cash.toggle_pin()
    assert window.sidebar.item_for(("statements", "cash")) is not None
    tile(page, "osv").toggle_pin()
    assert window.sidebar.item_for(("osv",)) is None
    assert catalog.pinned() == ["balance", "profit", "cash"]
    # a card is pinned too: the sidebar item asks the account, as from the page
    tile(page, "card").toggle_pin()
    assert window.sidebar.item_for(("pin", "card")) is not None
    window.unpin("card")  # the sidebar's menu «Убрать из боковой панели»
    assert window.sidebar.item_for(("pin", "card")) is None
    assert not tile(page, "card").pinned
    # another window (the next start) shows the same
    window.shutdown()
    again = MainWindow(window.workspace)
    qtbot.addWidget(again)
    again.start()
    keys = sidebar_keys(again)
    assert ("statements", "cash") in keys and ("osv",) not in keys
    again.shutdown()


@pytest.mark.parametrize("query", ["mənfəət", "menfeet", "прибыл", "ПРИБЫЛИ  убытки"])
def test_the_search_finds_the_profit_and_loss(window, query):
    page = hub(window)
    type_text(page.search, query)
    assert [t.report.id for t in page.found()] == ["profit"]
    page.search.returnPressed.emit()  # Enter: the first found
    statements = window.stack.currentWidget()
    assert isinstance(statements, StatementsPage) and statements.view == "profit"


def test_nothing_found_says_so(window):
    page = hub(window)
    type_text(page.search, "zzz")
    assert page.found() == []
    assert not page.nothing.isHidden()
    type_text(page.search, "")
    assert len(page.found()) == len(page.tiles)


def test_a_report_of_an_account_asks_the_account(window, monkeypatch):
    s = window.open_session
    account = s.catalog.by_code["60"].id
    asked = []

    def answer(catalog, kind, title, parent):
        asked.append((kind, title))
        return account

    monkeypatch.setattr(places, "ask_account", answer)
    window.open_catalog_report("card")
    page = window.stack.currentWidget()
    assert isinstance(page, CardPage) and page.account_id == account
    assert asked == [("card", "Карточка счёта")]
    monkeypatch.setattr(places, "ask_account", lambda *a: None)  # «Отмена»: nothing opens
    pages = len(window.pages)
    window.open_catalog_report("analysis")
    assert len(window.pages) == pages
    assert "analysis" not in catalog.recent()


def test_the_subconto_analysis_opens_as_one_page(window):
    """«Анализ субконто» asks nothing first: the directory is chosen on the page (D125);
    opened again, the same page comes back."""
    from modern_gl.desktop.reports_page import SubcontoAnalysisPage

    window.open_catalog_report("subconto_analysis")
    page = window.stack.currentWidget()
    assert isinstance(page, SubcontoAnalysisPage) and page.kind_id is not None
    assert catalog.recent()[0] == "subconto_analysis"
    pages = len(window.pages)
    window.open_catalog_report("subconto_analysis")
    assert len(window.pages) == pages and window.stack.currentWidget() is page


def test_the_account_is_typed_and_remembered(window, qtbot):
    s = window.open_session
    prompt = AccountPrompt(s.catalog, "subconto", "ОСВ по субконто")
    qtbot.addWidget(prompt)
    labels = [prompt.account.itemText(i) for i in range(prompt.account.count())]
    sixty = next(label for label in labels if label.startswith("60"))
    plain = [a.label for a in s.catalog.accounts.values() if a.sc_kinds[0] is None]
    assert plain and not set(plain) & set(labels)  # an account without a subconto: not offered
    type_text(prompt.account, sixty)
    prompt.account.editingFinished.emit()
    assert prompt.result() == AccountPrompt.DialogCode.Accepted
    assert s.catalog.accounts[prompt.chosen()].code.startswith("60")
    again = AccountPrompt(s.catalog, "card", "Карточка счёта")
    qtbot.addWidget(again)
    assert again.chosen() == prompt.chosen()  # the account asked last


def test_ctrl_k_finds_the_reports_by_name(window):
    palette = window.command_palette()
    assert palette is not None
    for query, title in (
        ("прибыл", "Прибыли и убытки"),
        ("mənfəət", "Прибыли и убытки"),
        ("субконто", "ОСВ по субконто"),
        ("карточка сч", "Карточка счёта"),
        ("отчёты", "Все отчёты"),
    ):
        palette.search.setText(query)
        assert title in [e.title for e in palette.entries_shown()], query
    palette.close()


def test_a_warehouse_only_company_has_no_reports_of_the_books(window):
    window.set_stock_only(True)
    page = hub(window)
    ids = {t.report.id for t in page.tiles}
    assert ids == {"reconcile_purchases", "reconcile_sales", "landed", "stock"}
    keys = sidebar_keys(window)
    assert HUB in keys and ("osv",) not in keys and ("statements", "balance") not in keys
    window.open_catalog_report("osv")  # not from Ctrl+K or a pin either
    assert not isinstance(window.stack.currentWidget(), StatementsPage)
    assert ("osv",) not in window.pages


def test_viewing_offers_nothing_that_writes(qtbot, tmp_path):
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("ДЕМО ООО")
    conn = connect(path)
    create_demo_company(Ledger(conn))
    conn.close()
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)
    page = hub(win)
    ids = {t.report.id for t in page.tiles}
    assert "reconcile_purchases" not in ids and "reconcile_sales" not in ids
    assert "osv" in ids
    win.shutdown()
