"""Warehouse reports: «Ведомость по складу», «Карточка товара», «Валовая прибыль по
товарам». The numbers are worked out by hand in `february`'s docstring."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.inventory import QUANTITY_FACTOR, SaleLine, TransferLine
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.stock_reports import GrossProfitPage, ItemCardPage, StockStatementPage
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.inventory import (
    BY_CUSTOMER,
    BY_WAREHOUSE,
    gross_profit,
    item_card,
    stock_statement,
)
from tests.test_sales import Shop, make_shop

Q = QUANTITY_FACTOR


@pytest.fixture
def february(conn) -> tuple[Shop, int]:
    """Classic chart, printers on «Əsas anbar»:
      10.01 bought 10 for 120.00 (12.00 each)
      20.01 sold 3 for 60.00 and a delivery for 25.00; cost 3 × 12.00 = 36.00
            → 7 for 84.00
      05.02 bought 5 for 75.00 → 12 for 159.00
      10.02 moved 4 to «Rezerv»: 159.00 × 4 / 12 = 53.00 → Əsas 8 for 106.00
      15.02 sold 2 for 50.00; cost 106.00 × 2 / 8 = 26.50 → Əsas 6 for 79.50
    At the end of February: Əsas 6 for 79.50, Rezerv 4 for 53.00 — 10 for 132.50, and 41
    holds 120.00 − 36.00 + 75.00 − 26.50 = 132.50."""
    shop = make_shop(conn, "classic")
    reserve = shop.inventory.add_warehouse(shop.company_id, "Rezerv")
    shop.receipt("2026-01-10", "10", "120")
    shop.sale(
        "2026-01-20",
        [
            SaleLine(shop.item, shop.main, "3", "60", "10.80"),
            SaleLine(None, None, None, "25", "4.50", "Çatdırılma"),
        ],
    )
    shop.receipt("2026-02-05", "5", "75")
    shop.inventory.post_transfer(
        shop.company_id, "2026-02-10", [TransferLine(shop.item, shop.main, reserve, "4")]
    )
    shop.sale("2026-02-15", [SaleLine(shop.item, shop.main, "2", "50", "9")])
    return shop, reserve


def figures(row) -> tuple[int, ...]:
    return (
        row.opening_quantity // Q,
        row.opening_amount,
        row.in_quantity // Q,
        row.in_amount,
        row.out_quantity // Q,
        row.out_amount,
        row.closing_quantity // Q,
        row.closing_amount,
    )


def test_statement_by_item_has_its_warehouses_under_it(february):
    """The item in all: 7 / 84.00 at the start; in 5 bought + 4 moved in = 9 for
    75.00 + 53.00 = 128.00; out 4 moved out + 2 sold = 6 for 53.00 + 26.50 = 79.50;
    10 / 132.50 at the end — what the books hold on 41."""
    shop, reserve = february
    statement = stock_statement(shop.ledger.conn, shop.company_id, "2026-02-01", "2026-02-28")
    item, main, rezerv = statement.rows
    assert (item.name, item.depth, item.unit_code) == ("Printer", 0, "əd")
    assert figures(item) == (7, 8_400, 9, 12_800, 6, 7_950, 10, 13_250)
    assert (main.name, main.depth, main.warehouse_id) == ("Əsas anbar", 1, shop.main)
    assert figures(main) == (7, 8_400, 5, 7_500, 6, 7_950, 6, 7_950)
    assert (rezerv.name, rezerv.warehouse_id) == ("Rezerv", reserve)
    assert figures(rezerv) == (0, 0, 4, 5_300, 0, 0, 4, 5_300)
    assert statement.total.closing_amount == 13_250
    assert statement.books_amount == 13_250


def test_statement_at_a_date_and_by_warehouse(february):
    """January alone: 10 bought for 120.00, 3 sold for 36.00, 7 for 84.00 left — on one
    warehouse, so the item's row is that warehouse's and nothing is under it. By warehouse
    for February: each warehouse with its items under it; a warehouse has no quantity
    (its items may have different units)."""
    shop, _ = february
    january = stock_statement(shop.ledger.conn, shop.company_id, "2026-01-01", "2026-01-31")
    (item,) = january.rows
    assert figures(item) == (0, 0, 10, 12_000, 3, 3_600, 7, 8_400)
    assert item.warehouse_id == shop.main
    assert january.books_amount == 8_400

    statement = stock_statement(
        shop.ledger.conn, shop.company_id, "2026-02-01", "2026-02-28", BY_WAREHOUSE
    )
    names = [(r.name, r.depth) for r in statement.rows]
    assert names == [("Əsas anbar", 0), ("Printer", 1), ("Rezerv", 0), ("Printer", 1)]
    main = statement.rows[0]
    assert not main.has_quantity and main.closing_amount == 7_950
    assert statement.rows[1].closing_quantity == 6 * Q


def test_statement_against_the_books_shows_a_difference(february):
    """A hand posting on 41 without the warehouse (Dt 41 / Kt 60 10.00) is in the books,
    not in stock: the books hold 142.50 against 132.50."""
    shop, _ = february
    conn = shop.ledger.conn
    (item_value,) = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()
    (place_value,) = conn.execute(
        "SELECT subconto_value_id FROM warehouses WHERE id = ?", (shop.main,)
    ).fetchone()
    by_hand = PostingInput(
        shop.acc["41"], shop.acc["60"], "10.00", (item_value, place_value), shop.supplier
    )
    shop.ledger.post_new(shop.company_id, "2026-02-20", [by_hand])
    statement = stock_statement(shop.ledger.conn, shop.company_id, "2026-02-01", "2026-02-28")
    assert (statement.total.closing_amount, statement.books_amount) == (13_250, 14_250)


def test_item_card_of_one_warehouse_and_of_all(february):
    """Əsas anbar in February: 7 / 84.00, bought → 12 / 159.00, moved out → 8 / 106.00,
    sold → 6 / 79.50. On all warehouses the transfer is out and in: 12 / 159.00 after it,
    10 / 132.50 at the end."""
    shop, _ = february
    card = item_card(
        shop.ledger.conn, shop.company_id, shop.item, shop.main, "2026-02-01", "2026-02-28"
    )
    assert (card.name, card.opening_quantity, card.opening_amount) == ("Printer", 7 * Q, 8_400)
    assert [
        (m.quantity // Q, m.amount, m.quantity_balance // Q, m.amount_balance) for m in card.lines
    ] == [
        (5, 7_500, 12, 15_900),
        (-4, -5_300, 8, 10_600),
        (-2, -2_650, 6, 7_950),
    ]
    assert [m.source.doc_type for m in card.lines] == ["receipt", "transfer", "sale"]

    every = item_card(
        shop.ledger.conn, shop.company_id, shop.item, None, "2026-02-01", "2026-02-28"
    )
    assert [m.amount_balance for m in every.lines][-1] == 13_250
    assert {m.warehouse for m in every.lines} == {"Əsas anbar", "Rezerv"}
    assert (every.closing_quantity, every.closing_amount) == (10 * Q, 13_250)


def test_gross_profit_by_item_and_by_customer(february):
    """January and February: printers 3 + 2 = 5 sold for 60.00 + 50.00 = 110.00, cost
    36.00 + 26.50 = 62.50, profit 47.50; the delivery 25.00 without cost. In all 135.00,
    62.50, 72.50. Both sales were to Alfa."""
    shop, _ = february
    rows = gross_profit(shop.ledger.conn, shop.company_id, "2026-01-01", "2026-02-28")
    printer, services, total = rows
    assert (printer.name, printer.quantity // Q, printer.revenue, printer.cost) == (
        "Printer",
        5,
        11_000,
        6_250,
    )
    assert printer.profit == 4_750
    assert (services.name, services.item_id, services.revenue, services.cost) == (
        "Услуги",
        None,
        2_500,
        0,
    )
    assert (total.is_total, total.revenue, total.cost, total.profit) == (True, 13_500, 6_250, 7_250)

    alfa, *items, total = gross_profit(
        shop.ledger.conn, shop.company_id, "2026-01-01", "2026-02-28", BY_CUSTOMER
    )
    assert (alfa.name, alfa.depth, alfa.revenue, alfa.profit) == ("Alfa", 0, 13_500, 7_250)
    assert [(r.name, r.depth) for r in items] == [("Printer", 1), ("Услуги", 1)]


@pytest.fixture
def window(qtbot, tmp_path):
    conn = connect(tmp_path / "ДЕМО ООО.gl")
    create_demo_company(Ledger(conn))
    conn.close()
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.show()
    yield win
    win.shutdown()


def test_the_statement_opens_the_card_and_the_card_the_document(window):
    """The demo's paper: bought 120 for 1 200.00 (10.01) and 50 for 500.00 (03.02), 30
    written off at 10.00 = 300.00 (20.02): January–February ends with 140 for 1 400.00, as
    on «Склад», and the account agrees. A double click on the paper opens its card, on a
    movement — the warehouse document."""
    window.session.working_date = date(2026, 2, 28)
    window.open_catalog_report("stock_statement")
    page = window.stack.currentWidget()
    assert isinstance(page, StockStatementPage)
    page.period.set_period(date(2026, 1, 1), date(2026, 2, 28))
    total = page.model.rows[-1]
    assert total.is_total and total.closing_amount == 140_000
    assert "✓" in page.footer.text()
    paper = page.model.rows[0]
    page.drill(paper)
    card = window.stack.currentWidget()
    assert isinstance(card, ItemCardPage) and card.item_id == paper.item_id
    assert card.model.rows[-1].amount_balance == 140_000
    movement = next(r for r in card.model.rows if r.document_id is not None)
    card.drill(movement)
    assert isinstance(window.stack.currentWidget(), InventoryDocumentPage)


def test_gross_profit_shows_the_services_sold(window):
    """The demo sold services only (1 000.00 without VAT): revenue without cost."""
    window.session.working_date = date(2026, 2, 28)
    window.open_catalog_report("gross_profit")
    page = window.stack.currentWidget()
    assert isinstance(page, GrossProfitPage)
    page.period.set_period(date(2026, 1, 1), date(2026, 2, 28))
    total = page.model.rows[-1]
    assert (total.revenue, total.cost, total.profit) == (100_000, 0, 100_000)
