"""The profit and loss by the elements of a directory in columns, its lines under the
groups of the chart, and a line's share of the revenue (D188): a restaurant with two
shops and a head office, the chart in the manner of the Uniform System of Accounts for
Restaurants — groups give the sections, «Lokasiya» on every income and expense account.

    3000 Sales (group)              4000 COGS (group)            5000 Labor (group)
      3000.1 Food sales               4100 Food cost (group)       5010 Wages
      3000.2 Beverage sales             4110 Meat                7000 Rent
                                        4130 Produce             9070 Accounting fees
                                      4200 Beverage cost         9080 Bank fees — no location

March (manat):
   1 Dt 50   Kt 3000.1 [Shop 1]   1 000     7 Dt 4200 [Shop 1] Kt 60      60
   2 Dt 50   Kt 3000.2 [Shop 1]     200     8 Dt 5010 [Shop 1] Kt 50     250
   3 Dt 50   Kt 3000.1 [Shop 2]     600     9 Dt 5010 [Shop 2] Kt 50     200
   4 Dt 4110 [Shop 1] Kt 60         300    10 Dt 7000 [Shop 1] Kt 50     100
   5 Dt 4130 [Shop 1] Kt 60          50    11 Dt 7000 [Shop 2] Kt 50      80
   6 Dt 4110 [Shop 2] Kt 60         150    12 Dt 9070 [Head Office] Kt 50  70
                                           13 Dt 9080 Kt 50               10

Columns: Head Office · Shop 1 · Shop 2 · not given · whole.
Revenue           0 · 1 200 · 600 ·  0 · 1 800
Cost of sales     0 ·  −410 · −150 ·  0 ·  −560      (300 + 50 + 60; 150)
Gross profit      0 ·   790 · 450 ·  0 · 1 240
Operating       −70 ·  −350 · −280 · −10 · −710      (250 + 100; 200 + 80; 70; 10)
Operating profit −70 ·  440 · 170 · −10 ·  530 = net
"""

from __future__ import annotations

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.reporting.columns import Amounts, share
from modern_gl.reporting.profit_loss import ACCOUNTS, ITEMS, profit_and_loss


@pytest.fixture
def restaurant(ledger: Ledger):
    cid = ledger.create_company("Restoran")
    location = ledger.add_subconto_kind(cid, None, "Lokasiya")
    shops = {
        n: ledger.add_subconto_value(cid, location, n) for n in ("Shop 1", "Shop 2", "Head Office")
    }
    acc: dict[str, int] = {}

    def account(code: str, name: str, parent: str | None = None, **kw) -> None:
        acc[code] = ledger.add_account(cid, code, name, parent=parent, **kw)

    account("50", "Cash", account_type="cash")
    account("60", "Suppliers", account_type="payable")
    account("3000", "Sales", is_group=True, account_type="sales")
    account("3000.1", "Food sales", "3000", subconto=[location])
    account("3000.2", "Beverage sales", "3000", subconto=[location])
    account("4000", "COGS", is_group=True, account_type="cost_of_sales")
    account("4100", "Food cost", "4000", is_group=True)
    account("4110", "Meat", "4100", subconto=[location])
    account("4130", "Produce", "4100", subconto=[location])
    account("4200", "Beverage cost", "4000", subconto=[location])
    account("5000", "Labor", is_group=True, account_type="operating_expense")
    account("5010", "Wages", "5000", subconto=[location])
    account("7000", "Rent", account_type="operating_expense", subconto=[location])
    account("9070", "Accounting fees", account_type="operating_expense", subconto=[location])
    account("9080", "Bank fees", account_type="operating_expense")

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)

    s1, s2, ho = shops["Shop 1"], shops["Shop 2"], shops["Head Office"]
    for posting in [
        p("50", "3000.1", "1000", ct_sc=[s1]),
        p("50", "3000.2", "200", ct_sc=[s1]),
        p("50", "3000.1", "600", ct_sc=[s2]),
        p("4110", "60", "300", [s1]),
        p("4130", "60", "50", [s1]),
        p("4110", "60", "150", [s2]),
        p("4200", "60", "60", [s1]),
        p("5010", "50", "250", [s1]),
        p("5010", "50", "200", [s2]),
        p("7000", "50", "100", [s1]),
        p("7000", "50", "80", [s2]),
        p("9070", "50", "70", [ho]),
        p("9080", "50", "10"),
    ]:
        ledger.post_new(cid, "2026-03-10", [posting])
    return ledger.conn, cid, location, shops


def m(*manat: int) -> Amounts:
    return Amounts(x * 100 for x in manat)


def test_a_column_per_shop_and_the_whole_last(restaurant):
    conn, cid, location, shops = restaurant
    pl = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", split=location)
    assert pl.split == [
        (shops["Head Office"], "Head Office"),
        (shops["Shop 1"], "Shop 1"),
        (shops["Shop 2"], "Shop 2"),
        (None, ""),
    ]
    assert [(ln.title, ln.amount) for ln in pl.lines] == [
        ("Выручка", m(0, 1200, 600, 0, 1800)),
        ("Себестоимость продаж", m(0, -410, -150, 0, -560)),
        ("Валовая прибыль", m(0, 790, 450, 0, 1240)),
        ("Операционные расходы", m(-70, -350, -280, -10, -710)),
        ("Операционная прибыль", m(-70, 440, 170, -10, 530)),
        ("Прибыль до налогообложения", m(-70, 440, 170, -10, 530)),
        ("Чистая прибыль (убыток)", m(-70, 440, 170, -10, 530)),
    ]


def test_the_whole_column_is_the_plain_report(restaurant):
    conn, cid, location, _ = restaurant
    split = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ITEMS, split=location)
    plain = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ITEMS)
    assert [(ln.title, ln.amount[4]) for ln in split.lines] == [
        (ln.title, ln.amount[0]) for ln in plain.lines
    ]
    assert not plain.split


def test_the_lines_open_under_the_groups_of_the_chart(restaurant):
    """A lone group under a line is not repeated (3000, 4000); Food cost adds up its
    accounts (300 + 50 + 150), its accounts one step deeper; Labor stands beside the
    accounts without a group."""
    conn, cid, _, _ = restaurant
    pl = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ACCOUNTS)
    rows = [(ln.kind, ln.depth, ln.title, ln.amount) for ln in pl.lines]
    assert rows[: rows.index(("subtotal", 0, "Валовая прибыль", m(1240)))] == [
        ("line", 0, "Выручка", m(1800)),
        ("account", 0, "3000.1  Food sales", m(1600)),
        ("account", 0, "3000.2  Beverage sales", m(200)),
        ("line", 0, "Себестоимость продаж", m(-560)),
        ("group", 0, "4100  Food cost", m(-500)),
        ("account", 1, "4110  Meat", m(-450)),
        ("account", 1, "4130  Produce", m(-50)),
        ("account", 0, "4200  Beverage cost", m(-60)),
    ]
    operating = rows.index(("line", 0, "Операционные расходы", m(-710)))
    assert rows[operating + 1 : operating + 6] == [
        ("group", 0, "5000  Labor", m(-450)),
        ("account", 1, "5010  Wages", m(-450)),
        ("account", 0, "7000  Rent", m(-180)),
        ("account", 0, "9070  Accounting fees", m(-70)),
        ("account", 0, "9080  Bank fees", m(-10)),
    ]


def test_items_keep_the_depth_of_their_account(restaurant):
    conn, cid, _, _ = restaurant
    pl = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ITEMS)
    items = [(ln.title, ln.depth, ln.amount) for ln in pl.lines if ln.kind == "item"]
    assert items[:3] == [("Shop 1", 0, m(1000)), ("Shop 2", 0, m(600)), ("Shop 1", 0, m(200))]
    assert ("Shop 1", 1, m(-300)) in items  # Meat under Food cost
    assert ("", 0, m(-10)) not in items  # Bank fees has no location: no items under it


def test_share_of_the_revenue():
    """Cost 410 of 1 200: 34.17 %; gross 790: 65.83 %; no revenue — no share."""
    assert share(-41_000, 120_000) == -3_417
    assert share(79_000, 120_000) == 6_583
    assert share(10_000, 0) is None
    assert share(0, 120_000) == 0


# ---- the page ---------------------------------------------------------------------------


@pytest.fixture
def window(statements_window):
    return statements_window


def test_the_page_splits_the_profit_and_loss_and_shows_the_share(window, qtbot):
    """«Колонки: По субконто: …» — a column per cost item of the demo and «Итого», the
    whole being the sum of the elements; «Процент от выручки» puts a «%» after each
    figure, the revenue being 100 % of itself; the balance sheet knows no split."""
    from datetime import date

    from modern_gl.desktop.reports_page import StatementsPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    page.profit_button.click()
    page.period.set_period(date(2026, 1, 1), date(2026, 3, 31))
    directories = dict(page._directories())
    assert "Статьи затрат" in directories.values()  # the cost items of 26 and 44
    kind_id, name = next((k, n) for k, n in directories.items() if n == "Статьи затрат")
    page.columns.choose("subconto", name)
    assert page.columns.kind_id() == kind_id
    qtbot.waitUntil(lambda: bool(page.model.columnCount() > 2 and page.split))
    titles = [page.model.title(i) for i in range(page.model.columnCount())]
    assert titles[0] == "Статья" and titles[-1] == "Итого"
    assert titles[1:] == ["Аренда офиса", "Материальные расходы", "Не указано", "Итого"]
    operating = next(r for r in page.model.rows if r.title == "Операционные расходы")
    assert tuple(operating.amount) == (-25_000, -30_000, 0, -55_000)
    net = page.model.rows[-1]
    assert net.title == "Чистая прибыль (убыток)"
    assert net.amount[-1] == sum(net.amount[:-1])
    assert page.columns.button.text().startswith(f"Колонки: По субконто: {name}")

    page.columns.toggle_percent()
    qtbot.waitUntil(lambda: page.model.title(2) == "%")
    revenue = next(r for r in page.model.rows if r.account_type == "sales" and r.kind == "line")
    whole, first = page.model.columns[-1], page.model.columns[2]
    assert whole.title == "%" and whole.value is not None and first.value is not None
    assert whole.value(revenue) == 10_000  # the share in «Итого»: revenue 100 %
    assert whole.value(operating) == -5_500  # expenses −55 %
    assert first.value(revenue) is None  # no revenue in «Аренда офиса»

    page.balance_button.click()  # one column: the split is of the profit and loss only
    qtbot.waitUntil(lambda: page.model.columnCount() == 2)
    assert page.columns.mode == "subconto"
    page.columns.toggle_percent()
    page.columns.choose("one")
    again = StatementsPage(window.session)
    assert (again.columns.mode, again.columns.percent) == ("one", False)
    again.deleteLater()
