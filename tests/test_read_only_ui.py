"""A company open for viewing only (D80): every page opens, nothing offers to change it."""

from datetime import date

import pytest
from PySide6.QtWidgets import QPushButton

from modern_gl.application.queries import list_documents
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import PLACE_KEYS, MainWindow
from modern_gl.i18n import tr
from modern_gl.reporting.trade import PURCHASE, SALE, trade_documents
from tests.helpers.qt import running_app

# what changes a company: none of it is shown while viewing
WRITES = [
    "Провести",
    "Сохранить черновик",
    "Удалить",
    "Отменить проведение",
    "+ Новый счёт",
    "+ Новый элемент",
    "+ Новый справочник",
    "+ Новый шаблон",
    "+ Курс",
    "+ Товар",
    "+ Приход денег",
    "+ Расход денег",
    "Импорт из Excel…",
    "E-qaimə с портала…",
    "+",
]


@pytest.fixture
def company(tmp_path, make_demo):
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("ДЕМО ООО")
    make_demo(path)
    return ws, path


@pytest.fixture
def viewer(qtbot, company):
    ws, path = company
    theme.apply(running_app())
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)
    win.open_session.working_date = date(2026, 3, 5)
    win.show()
    yield win
    win.shutdown()


def offered_writes(win) -> list[str]:
    page = win.stack.currentWidget()
    words = {tr(w) for w in WRITES}
    return sorted(
        b.text() for b in page.findChildren(QPushButton) if b.isVisible() and b.text() in words
    )


def test_the_company_is_shown_as_viewed(viewer):
    assert viewer.open_session.read_only
    assert viewer.sidebar.viewing.isVisible()
    assert tr("только просмотр") in viewer.windowTitle()


@pytest.mark.parametrize("key", PLACE_KEYS)
def test_every_place_opens_without_offering_changes(viewer, key):
    viewer.show_place(key)
    assert offered_writes(viewer) == []


def test_every_document_opens_without_offering_changes(viewer):
    s = viewer.open_session
    for doc in list_documents(s.conn, s.company_id):
        viewer.open_document(doc.id)
        assert offered_writes(viewer) == [], doc.number
    for kind in (PURCHASE, SALE):
        for row in trade_documents(s.conn, s.company_id, kind):
            viewer.open_inventory_document(row.id)
            assert offered_writes(viewer) == [], row.number


def test_nothing_new_is_started(viewer):
    pages = len(viewer.pages)
    viewer.new_document()
    viewer.new_bank_operation()
    viewer.new_conversion()
    viewer.new_inventory_document("receipt")
    viewer.open_template(None)
    viewer.show_import()
    assert len(viewer.pages) == pages
    assert viewer.toast.message() == tr("Компания открыта только для просмотра")


def test_the_file_is_left_as_it_was(qtbot, company):
    ws, path = company
    before = path.read_bytes()
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)
    for key in PLACE_KEYS:
        win.show_place(key)
    win.reread()
    win.shutdown()
    assert path.read_bytes() == before
    assert ws.backups(path) == []  # closing a viewed company makes no backup


def test_working_on_a_company_again_after_viewing(qtbot, company):
    ws, path = company
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.view_company(path)
    win.open_company(path)
    assert not win.open_session.read_only
    assert not win.sidebar.viewing.isVisibleTo(win.sidebar)
    win.shutdown()
