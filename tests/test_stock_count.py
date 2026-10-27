"""«Инвентаризация»: the counted quantity against the books makes a mədaxil «Излишки» and
a write-off — the numbers worked out by hand in each docstring."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.inventory import QUANTITY_FACTOR, CountedLine, ReceiptLine
from modern_gl.desktop.stock_count_page import StockCountPage
from modern_gl.desktop.stock_count_page.model import QUANTITY
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from tests.helpers.sales import Shop, make_shop

Q = QUANTITY_FACTOR


@pytest.fixture
def shop(conn) -> tuple[Shop, int]:
    """Printers: 10 for 120.00 (12.00 each); toner: 4 for 20.00 (5.00 each)."""
    shop = make_shop(conn, "classic")
    unit = conn.execute("SELECT id FROM inventory_units WHERE company_id = ?", (shop.company_id,))
    toner = shop.inventory.add_item(shop.company_id, "Toner", unit.fetchone()["id"], shop.acc["41"])
    shop.receipt("2026-01-10", "10", "120")
    shop.inventory.post_receipt(
        shop.company_id,
        "2026-01-10",
        [ReceiptLine(toner, shop.main, "4", "20")],
        shop.acc["60"],
        shop.supplier,
    )
    return shop, toner


def balances(shop: Shop) -> dict[int, tuple[int, int]]:
    return {
        b.item_id: (b.quantity // Q, b.amount)
        for b in stock_balances(shop.ledger.conn, shop.company_id)
    }


def test_count_posts_the_surplus_and_the_shortage(shop):
    """Counted 8 printers (2 short: 2 × 12.00 = 24.00, Dt 46 / Kt 41) and 6 toners (2
    extra at the average 5.00 = 10.00, Dt 41 / Kt 80 «излишки»). Printers 8 for 96.00,
    toner 6 for 30.00."""
    shop, toner = shop
    result = shop.inventory.post_stock_count(
        shop.company_id,
        "2026-01-20",
        shop.main,
        [CountedLine(shop.item, "8"), CountedLine(toner, "6")],
        shop.acc["46"],
    )
    assert balances(shop) == {shop.item: (8, 9_600), toner: (6, 3_000)}
    assert shop.postings(result.shortage_document_id) == [("46", "41", 2_400, "Printer", None)]
    assert shop.postings(result.surplus_document_id) == [("41", "80", 1_000, "Toner", None)]
    surplus = shop.inventory.load_document(shop.company_id, result.surplus_document_id)
    assert (surplus.doc_type, surplus.incoming_reason) == ("incoming", "surplus")
    assert surplus.memo == "Инвентаризация · Əsas anbar"


def test_count_looks_at_the_day_and_a_surplus_without_stock_needs_an_amount(shop):
    """On 05.01 nothing was there yet: 1 printer counted needs its value — 15.00 given.
    Later documents are recalculated: printers 11 for 135.00."""
    shop, _ = shop
    with pytest.raises(ValidationError, match="укажите сумму"):
        shop.inventory.post_stock_count(
            shop.company_id, "2026-01-05", shop.main, [CountedLine(shop.item, "1")], None
        )
    shop.inventory.post_stock_count(
        shop.company_id, "2026-01-05", shop.main, [CountedLine(shop.item, "1", "15")], None
    )
    assert balances(shop)[shop.item] == (11, 13_500)


def test_count_that_agrees_or_has_no_account_posts_nothing(shop):
    shop, toner = shop
    with pytest.raises(ValidationError, match="проводить нечего"):
        shop.inventory.post_stock_count(
            shop.company_id, "2026-01-20", shop.main, [CountedLine(toner, "4")], None
        )
    with pytest.raises(ValidationError, match="списать недостачу"):  # all or nothing
        shop.inventory.post_stock_count(
            shop.company_id,
            "2026-01-20",
            shop.main,
            [CountedLine(toner, "6"), CountedLine(shop.item, "9")],
            None,
        )
    assert balances(shop) == {shop.item: (10, 12_000), toner: (4, 2_000)}


def test_the_page_puts_the_books_in_and_posts_what_was_typed(demo_window):
    """The demo's paper on 28.02: 140 for 1 400.00 (10.00 each) — put in as counted.
    Typed 138: 2 short for 20.00, written off; «Склад» shows 138 for 1 380.00."""
    demo_window.session.working_date = date(2026, 2, 28)
    demo_window.show_place(("inventory",))
    demo_window.stack.currentWidget().operation("count")
    page = demo_window.stack.currentWidget()
    assert isinstance(page, StockCountPage)
    (paper,) = page.model.rows
    assert (paper.book, paper.counted, paper.value) == (140 * Q, 140 * Q, 140_000)
    assert not page.post_button.isEnabled()  # nothing differs yet
    page.model.setData(page.model.index(0, page.model.columns.index(QUANTITY)), 138 * Q)
    assert page.totals.text() == "Недостача: 1 на 20.00"
    page.post()
    assert not page.open_shortage.isHidden() and page.open_surplus.isHidden()
    assert page.model.rows[0].book == 138 * Q  # read again: the books agree now
    (balance,) = stock_balances(demo_window.session.conn, demo_window.session.company_id)
    assert (balance.quantity, balance.amount) == (138 * Q, 138_000)
