"""Every page the window shows speaks the page protocol (D160): the window asks nothing
else of a page, so a page missing a method would fail here, not on closing."""

from modern_gl.application.queries import list_documents
from modern_gl.desktop.main_window import PLACE_KEYS
from modern_gl.desktop.page import Page, PageWidget
from modern_gl.reporting.trade import PURCHASE, SALE, trade_documents


def open_everything(win) -> None:
    s = win.open_session
    for key in PLACE_KEYS:
        win.show_place(key)
    for doc in list_documents(s.conn, s.company_id):
        win.open_document(doc.id)
    for kind in (PURCHASE, SALE):
        for row in trade_documents(s.conn, s.company_id, kind):
            win.open_inventory_document(row.id)
    win.new_document()
    win.new_conversion()
    win.new_bank_operation()
    win.new_inventory_document("receipt")
    win.open_template(None)
    win.show_import()
    win.open_stock_count()
    win.open_books()


def test_every_page_speaks_the_protocol(demo_window):
    open_everything(demo_window)
    assert len(demo_window.pages) > 20
    for key, page in demo_window.pages.items():
        assert isinstance(page, PageWidget), key
        assert isinstance(page, Page), key
        assert page.key == key
        assert isinstance(page.title(), str) and page.title(), key
        assert page.is_dirty() in (False, True), key
    # the window's two calls that reach every page at once
    for page in list(demo_window.pages.values()):
        page.activated()
        page.on_postings_changed(1)
