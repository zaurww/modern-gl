"""Финансовая отчётность (D99): the balance sheet and the profit and loss by account type.

A small company, worked out by hand (amounts in manat):
   1 15.01  Dt 51       Kt 80        10 000   capital paid in
   2 20.01  Dt 01       Kt 60 [A]     3 000   equipment from supplier A
   3 25.01  Dt 60 [B]   Kt 51           500   an advance to supplier B
   4 01.02  Dt 41       Kt 60 [A]     2 000   goods from A
   5 10.02  Dt 62 [C]   Kt 90.1       4 000   a sale to C
   6 10.02  Dt 90.2     Kt 41         1 500   its cost
   7 12.02  Dt 51       Kt 62 [C]     1 000   C pays a part
   8 15.02  Dt 26       Kt 02           100   depreciation
   9 20.02  Dt 26       Kt 76           300   an expense owed (76 has no type)
  10 25.02  Dt 50       Kt 91.1          50   other income in cash
  11 28.02  Dt 90.1     Kt 99         4 000   sales closed into the result
  12 28.02  Dt 99       Kt 90.2       1 500   cost closed into the result

Balance on 28.02: current assets — cash 50, bank 10 500, receivable 3 000, advance paid
500 (B's debit balance on 60), inventory 500 = 14 550; long-term — fixed assets 3 000 −
100 = 2 900; assets 17 450. Current liabilities — payable 5 000, untyped 300 = 5 300.
Equity — capital 10 000, result (99) 2 500, profit not closed: 26 (−400) + 91.1 (+50) =
−350; 12 150. 5 300 + 12 150 = 17 450.

Profit and loss of February: sales 4 000, cost −1 500 (the closing at 28.02 is not
income), gross 2 500; operating expenses −400 and other income 50 — both operating in
IFRS 18 (D128) → operating profit 2 150 = before tax = net. January has none."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.reporting.profit_loss import TITLES, profit_and_loss
from modern_gl.reporting.statements import balance_sheet


@pytest.fixture
def books(ledger: Ledger):
    cid = ledger.create_company("Тест")
    cp = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    a, b, c = (ledger.add_subconto_value(cid, cp, n) for n in ("A", "B", "C"))
    acc = {}
    for code, kind, extra in [
        ("50", "cash", {}),
        ("51", "bank", {}),
        ("01", "fixed_asset", {}),
        ("02", "fixed_asset", {"contra": True}),
        ("41", "inventory", {}),
        ("60", "payable", {"subconto": [cp], "two_sided": True}),
        ("62", "receivable", {"subconto": [cp], "two_sided": True}),
        ("80", "share_capital", {}),
        ("90.1", "sales", {}),
        ("90.2", "cost_of_sales", {}),
        ("26", "operating_expense", {}),
        ("91.1", "other_income", {}),
        ("99", "profit_loss", {}),
    ]:
        acc[code] = ledger.add_account(cid, code, code, account_type=kind, **extra)
    acc["76"] = ledger.add_account(cid, "76", "76", account_class="liability")

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)

    for day, posting in [
        ("2026-01-15", p("51", "80", "10000")),
        ("2026-01-20", p("01", "60", "3000", ct_sc=[a])),
        ("2026-01-25", p("60", "51", "500", dt_sc=[b])),
        ("2026-02-01", p("41", "60", "2000", ct_sc=[a])),
        ("2026-02-10", p("62", "90.1", "4000", dt_sc=[c])),
        ("2026-02-10", p("90.2", "41", "1500")),
        ("2026-02-12", p("51", "62", "1000", ct_sc=[c])),
        ("2026-02-15", p("26", "02", "100")),
        ("2026-02-20", p("26", "76", "300")),
        ("2026-02-25", p("50", "91.1", "50")),
        ("2026-02-28", p("90.1", "99", "4000")),
        ("2026-02-28", p("99", "90.2", "1500")),
    ]:
        ledger.post_new(cid, day, [posting])
    return ledger.conn, cid


def shown(statement) -> list[tuple[str, int | None]]:
    return [(ln.title, ln.amount if ln.kind != "heading" else None) for ln in statement.lines]


def test_balance_sheet_by_type(books):
    conn, cid = books
    sheet = balance_sheet(conn, cid, "2026-02-28")
    assert shown(sheet) == [
        ("Активы", None),
        ("Оборотные активы", None),
        ("Касса", 5_000),
        ("Банковские счета", 1_050_000),
        ("Покупатели и заказчики", 300_000),
        ("Авансы выданные", 50_000),
        ("Запасы", 50_000),
        ("Оборотные активы", 1_455_000),
        ("Долгосрочные активы", None),
        ("Основные средства", 290_000),
        ("Долгосрочные активы", 290_000),
        ("Итого активы", 1_745_000),
        ("Обязательства и капитал", None),
        ("Краткосрочные обязательства", None),
        ("Поставщики и подрядчики", 500_000),
        ("Счета без типа", 30_000),
        ("Краткосрочные обязательства", 530_000),
        ("Капитал", None),
        ("Уставный капитал", 1_000_000),
        ("Финансовый результат", 250_000),
        ("Прибыль (убыток) текущего периода", -35_000),
        ("Капитал", 1_215_000),
        ("Итого обязательства и капитал", 1_745_000),
    ]
    assert sheet.unbalanced == 0


def test_profit_and_loss_leaves_out_the_closing(books):
    conn, cid = books
    february = profit_and_loss(conn, cid, "2026-02-01", "2026-02-28")
    assert shown(february) == [
        ("Выручка", 400_000),
        ("Себестоимость продаж", -150_000),
        ("Валовая прибыль", 250_000),
        ("Операционные расходы", -40_000),
        ("Прочие доходы", 5_000),
        ("Операционная прибыль", 215_000),
        ("Прибыль до налогообложения", 215_000),
        ("Чистая прибыль (убыток)", 215_000),
    ]
    january = profit_and_loss(conn, cid, "2026-01-01", "2026-01-31")
    assert january.lines[-1].amount == 0


def code(line) -> str:
    """An account line by its code («62  62» — the test accounts are named by code)."""
    return line.title.split()[0] if line.kind == "account" else line.title


def test_a_balance_line_opens_into_its_accounts(books):
    """Fixed assets 2 900 = 01 3 000 − 02 100; 60 is in two lines: A's debt 5 000 among the
    liabilities, B's advance 500 among the assets; 76 under «Счета без типа» (D102)."""
    from modern_gl.reporting.statements import ACCOUNTS

    conn, cid = books
    sheet = balance_sheet(conn, cid, "2026-02-28", detail=ACCOUNTS)
    rows = [(ln.kind, code(ln), ln.amount) for ln in sheet.lines]
    fixed = rows.index(("line", "Основные средства", 290_000))
    assert rows[fixed + 1 : fixed + 3] == [("account", "01", 300_000), ("account", "02", -10_000)]
    advance = rows.index(("line", "Авансы выданные", 50_000))
    assert rows[advance + 1] == ("account", "60", 50_000)
    untyped = rows.index(("line", "Счета без типа", 30_000))
    assert rows[untyped + 1] == ("account", "76", 30_000)
    assert sheet.unbalanced == 0
    assert [ln for ln in sheet.lines if ln.kind != "account"] == balance_sheet(
        conn, cid, "2026-02-28"
    ).lines


def test_the_ifrs_book_adds_its_adjustments(books, ledger):
    conn, cid = books
    ledger.set_parallel_books(cid, True)
    inventory, expense = (
        conn.execute(
            "SELECT id FROM accounts WHERE company_id = ? AND code = ?", (cid, c)
        ).fetchone()[0]
        for c in ("41", "26")
    )
    # IFRS writes the goods down by 200
    ledger.post_new(
        cid, "2026-02-28", [PostingInput(expense, inventory, "200")], "МСФО", "ifrs_adj"
    )
    common = balance_sheet(conn, cid, "2026-02-28")
    ifrs = balance_sheet(conn, cid, "2026-02-28", ("common", "ifrs_adj"))
    assert dict(shown(common))["Запасы"] == 50_000
    assert dict(shown(ifrs))["Запасы"] == 30_000
    assert dict(shown(ifrs))["Прибыль (убыток) текущего периода"] == -55_000
    assert ifrs.unbalanced == 0
    pl = profit_and_loss(conn, cid, "2026-02-01", "2026-02-28", ("common", "ifrs_adj"))
    assert pl.lines[-1].amount == 195_000


def test_every_title_of_the_statements_has_azerbaijani_translation(books):
    from modern_gl.i18n_az import AZ

    conn, cid = books
    titles = {ln.title for ln in balance_sheet(conn, cid, "2026-02-28").lines}
    titles |= {ln.title for ln in profit_and_loss(conn, cid, "2026-01-01", "2026-12-31").lines}
    titles |= {"Прибыль до финансирования и налога на прибыль", "НДС с продаж"}
    titles |= set(TITLES.values())
    assert sorted(t for t in titles if t not in AZ) == []


# ---- the short chart (1C 7.7 «classic»): everything through 46 and 80 (D102) ----------
#
#   1 05.03  Dt 50             Kt 46            1 180   a sale for cash, with ƏDV
#   2 05.03  Dt 46             Kt 68.2            180   its ƏDV (68.2 — the output VAT role)
#   3 05.03  Dt 46             Kt 41              600   its cost
#   4 10.03  Dt 26 [Аренда]    Kt 50              100
#   5 12.03  Dt 26 [Связь]     Kt 50               40
#   6 15.03  Dt 44 [Транспорт] Kt 50               30
#   7 20.03  Dt 80             Kt 50                5   a bank fee straight to the result
#   8 22.03  Dt 50             Kt 80                8   an exchange gain, the same
#   9 31.03  Dt 46             Kt 26 [Аренда]     100   the month's expenses closed into 46
#  10 31.03  Dt 46             Kt 26 [Связь]       40
#  11 31.03  Dt 46             Kt 44 [Транспорт]   30
#  12 31.03  Dt 46             Kt 80              230   the result: 1 180 − 180 − 600 − 170
#  13 31.03  Dt 80             Kt 68.3             20   the profit tax
#
# Profit and loss of March: revenue 1 180 − ƏDV 180 = 1 000 (IFRS 15.47, D128), cost −600,
# gross 400; operating expenses −170 (26: −140 = rent −100 + communication −40; 44: −30),
# other income 8, other expense −5 — all operating (IFRS 18) → 233 = before tax; tax −20
# → net 213 — what is left on 80: 230 + 8 − 5 − 20.
# Before D102 the closing 9–11 hid the expenses inside 46 and 7, 8, 13 were not read.


@pytest.fixture
def classic(ledger: Ledger):
    from modern_gl.application.chart_csv import apply_chart_template

    cid = ledger.create_company("Классика")
    apply_chart_template(ledger, cid, "classic", "ru")

    def value(kind: str, name: str) -> int:
        return ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name)

    rent, phone, transport = (value("cost_item", n) for n in ("Аренда", "Связь", "Транспорт"))
    goods = [value("item", "Бумага"), value("warehouse", "Склад")]
    codes = ("26", "41", "44", "46", "50", "68.2", "68.3", "80")
    acc = {c: ledger.account_id(cid, c) for c in codes}

    def p(dt, ct, amount, dt_sc=(), ct_sc=()):
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)

    ledger.post_new(cid, "2026-02-27", [p("41", "50", "600", goods)])  # the goods
    for day, posting in [
        ("2026-03-05", p("50", "46", "1180")),
        ("2026-03-05", p("46", "68.2", "180")),
        ("2026-03-05", p("46", "41", "600", ct_sc=goods)),
        ("2026-03-10", p("26", "50", "100", [rent])),
        ("2026-03-12", p("26", "50", "40", [phone])),
        ("2026-03-15", p("44", "50", "30", [transport])),
        ("2026-03-20", p("80", "50", "5")),
        ("2026-03-22", p("50", "80", "8")),
        ("2026-03-31", p("46", "26", "100", ct_sc=[rent])),
        ("2026-03-31", p("46", "26", "40", ct_sc=[phone])),
        ("2026-03-31", p("46", "44", "30", ct_sc=[transport])),
        ("2026-03-31", p("46", "80", "230")),
        ("2026-03-31", p("80", "68.3", "20")),
    ]:
        ledger.post_new(cid, day, [posting])
    return ledger.conn, cid


def test_the_short_chart_shows_the_expenses_where_they_were_spent(classic):
    conn, cid = classic
    march = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31")
    assert shown(march) == [
        ("Выручка", 100_000),
        ("Себестоимость продаж", -60_000),
        ("Валовая прибыль", 40_000),
        ("Операционные расходы", -17_000),
        ("Прочие доходы", 800),
        ("Прочие расходы", -500),
        ("Операционная прибыль", 23_300),
        ("Прибыль до налогообложения", 23_300),
        ("Налог на прибыль", -2_000),
        ("Чистая прибыль (убыток)", 21_300),
    ]


def test_a_line_opens_into_its_accounts_and_their_items(classic):
    from modern_gl.reporting.profit_loss import ACCOUNTS, ITEMS

    conn, cid = classic

    def part(statement, title: str, size: int):
        start = next(i for i, ln in enumerate(statement.lines) if ln.title == title)
        return [
            (ln.kind, ln.title.split()[0], ln.amount)
            for ln in statement.lines[start : start + size]
        ]

    accounts = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ACCOUNTS)
    # the only account of a line is not repeated under it: the line itself leads to it
    assert part(accounts, "Себестоимость продаж", 3) == [
        ("line", "Себестоимость", -60_000),
        ("subtotal", "Валовая", 40_000),
        ("line", "Операционные", -17_000),
    ]
    cost = next(ln for ln in accounts.lines if ln.title == "Себестоимость продаж")
    assert cost.account_id == ledger_account(conn, cid, "46")
    items = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ITEMS)
    assert part(items, "Операционные расходы", 6) == [
        ("line", "Операционные", -17_000),
        ("account", "26", -14_000),
        ("item", "Аренда", -10_000),
        ("item", "Связь", -4_000),
        ("account", "44", -3_000),
        ("item", "Транспорт", -3_000),
    ]
    assert items.lines[-1].amount == 21_300  # the detail does not change the sums


def ledger_account(conn, cid: int, code: str) -> int:
    return Ledger(conn).account_id(cid, code)


def test_a_cost_written_straight_to_the_sales_account_is_cost_of_sales(classic):
    """Dt 46 Kt 60: a carriage of goods already sold, written on the sales account — a
    cost of sales, not less revenue (demo year: «Daşınma xərcləri», D102)."""
    conn, cid = classic
    acc = {c: ledger_account(conn, cid, c) for c in ("46", "60", "80")}
    ledger = Ledger(conn)
    carrier = ledger.add_subconto_value(
        cid, ledger.subconto_kind_id(cid, "counterparty"), "Перевозчик"
    )
    ledger.post_new(cid, "2026-04-10", [PostingInput(acc["46"], acc["60"], "50", (), [carrier])])
    ledger.post_new(cid, "2026-04-30", [PostingInput(acc["80"], acc["46"], "50")])
    april = profit_and_loss(conn, cid, "2026-04-01", "2026-04-30")
    assert shown(april)[:2] == [("Себестоимость продаж", -5_000), ("Валовая прибыль", -5_000)]
    assert april.lines[-1].amount == -5_000


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, make_demo):
    from datetime import date

    from PySide6.QtWidgets import QApplication, QMessageBox

    from modern_gl.application.workspace import Workspace
    from modern_gl.desktop import theme
    from modern_gl.desktop.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def test_the_page_switches_between_the_balance_and_the_profit(window, qtbot):
    from modern_gl.desktop.reports_page import StatementsPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    qtbot.waitUntil(lambda: bool(page.model.rows))
    assert page.model.rows[0].title == "Активы"
    assert page.footer.text().startswith("Актив и пассив сходятся")
    page.profit_button.click()
    qtbot.waitUntil(lambda: page.model.rows[0].title != "Активы")
    assert page.model.rows[-1].title == "Чистая прибыль (убыток)"
    window.set_stock_only(True)  # the books are not shown: no statements either
    assert window.sidebar.item_for(("statements",)) is None


def test_a_line_of_the_page_leads_to_the_card(window, qtbot):
    """«По статьям»: an item of an expense account; a double click — its card with only
    that item; the page remembers the view and the detail (D102, D106)."""
    from modern_gl.desktop.reports_page import StatementsPage
    from modern_gl.desktop.reports_page.account import CardPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    page.profit_button.click()
    page.detail_buttons["items"].click()
    qtbot.waitUntil(lambda: any(r.kind == "item" for r in page.model.rows))
    item = next(r for r in page.model.rows if r.kind == "item")
    assert page.model.rows[page.model.rows.index(item) - 1].kind in ("line", "account", "item")
    page.drill(item)
    card = window.stack.currentWidget()
    assert isinstance(card, CardPage)
    assert card.account_id == item.account_id
    assert card.params.subconto == (item.value_id,)
    again = StatementsPage(window.session)
    assert (again.view, again.detail) == ("profit", "items")
    again.deleteLater()


def test_the_page_by_months_leads_to_the_card_of_a_month(window, qtbot):
    """«Колонки: По месяцам» on January–March: a column per month and «Итого»; a double
    click on February of an account (or a line of one account) — its card for February
    (D107)."""
    from modern_gl.desktop.reports_page import StatementsPage
    from modern_gl.desktop.reports_page.account import CardPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    page.profit_button.click()
    page.detail_buttons["accounts"].click()
    page.period.set_period(date(2026, 1, 1), date(2026, 3, 31))
    page.columns.choose("months")
    qtbot.waitUntil(lambda: page.model.columnCount() == 5)
    titles = [page.model.title(i) for i in range(5)]
    assert titles == ["Статья", "Январь", "Февраль", "Март", "Итого"]
    account = next(r for r in page.model.rows if r.account_id is not None)
    row = page.model.rows.index(account)
    page.table.setCurrentIndex(page.model.index(row, 2))
    page.drill(account)
    card = window.stack.currentWidget()
    assert isinstance(card, CardPage)
    assert (card.params.date_from, card.params.date_to) == (date(2026, 2, 1), date(2026, 2, 28))
    again = StatementsPage(window.session)
    assert again.columns.mode == "months"  # remembered
    again.deleteLater()


def test_balance_sheet_on_two_days(books):
    """D107: a column per day. On 31.01: bank 10 000 − 500 = 9 500, B's advance 500 →
    current 10 000; equipment 3 000; A is owed 3 000, capital 10 000 → 13 000 both sides.
    28.02 — as above."""
    from modern_gl.reporting.columns import Amounts

    conn, cid = books
    sheet = balance_sheet(conn, cid, "2026-02-28", days=["2026-01-31", "2026-02-28"])
    figures = {ln.title: tuple(ln.amount) for ln in sheet.lines if ln.kind != "heading"}
    assert figures["Касса"] == (0, 5_000)
    assert figures["Банковские счета"] == (950_000, 1_050_000)
    assert figures["Авансы выданные"] == (50_000, 50_000)
    assert figures["Основные средства"] == (300_000, 290_000)
    assert figures["Итого активы"] == (1_300_000, 1_745_000)
    assert figures["Поставщики и подрядчики"] == (300_000, 500_000)
    assert figures["Прибыль (убыток) текущего периода"] == (0, -35_000)
    assert figures["Итого обязательства и капитал"] == (1_300_000, 1_745_000)
    assert sheet.unbalanced == Amounts((0, 0))
    # the last column is the balance on its day read alone
    alone = balance_sheet(conn, cid, "2026-02-28")
    assert [(ln.title, ln.amount[1]) for ln in sheet.lines] == [
        (ln.title, ln.amount[0]) for ln in alone.lines
    ]


def test_profit_and_loss_by_months_and_the_whole(books):
    """January, February and the whole: the whole is the report of the two months, and
    each line's months add up to it."""
    from modern_gl.reporting.columns import MONTHS, column_periods

    conn, cid = books
    periods = column_periods(MONTHS, (date(2026, 1, 1), date(2026, 2, 28)))
    pl = profit_and_loss(conn, cid, "2026-01-01", "2026-02-28", periods=periods)
    figures = {ln.title: tuple(ln.amount) for ln in pl.lines}
    assert figures["Выручка"] == (0, 400_000, 400_000)
    assert figures["Себестоимость продаж"] == (0, -150_000, -150_000)
    assert figures["Операционные расходы"] == (0, -40_000, -40_000)
    assert figures["Чистая прибыль (убыток)"] == (0, 215_000, 215_000)
    for ln in pl.lines:
        assert ln.amount[0] + ln.amount[1] == ln.amount[2]


def test_cash_flow_by_months(books):
    """Money: January +10 000 capital (financing), −500 the advance to B (operating);
    February +1 000 from C, +50 other income (operating). The start of February is the
    end of January; the whole begins at 0 and ends at 10 550."""
    from modern_gl.reporting.cash_flow import cash_flow
    from modern_gl.reporting.columns import MONTHS, column_periods

    conn, cid = books
    periods = column_periods(MONTHS, (date(2026, 1, 1), date(2026, 2, 28)))
    flow = cash_flow(conn, cid, "2026-01-01", "2026-02-28", periods=periods)
    figures = {ln.title: tuple(ln.amount) for ln in flow.lines if ln.kind != "heading"}
    assert figures["Деньги на начало периода"] == (0, 950_000, 0)
    assert figures["Чистый поток от операционной деятельности"] == (-50_000, 105_000, 55_000)
    assert figures["Чистый поток от финансовой деятельности"] == (1_000_000, 0, 1_000_000)
    assert figures["Деньги на конец периода"] == (950_000, 1_055_000, 1_055_000)
    assert not flow.unbalanced


def test_february_against_january(books):
    from modern_gl.reporting.columns import PREVIOUS, column_periods, difference, percent

    conn, cid = books
    periods = column_periods(PREVIOUS, (date(2026, 2, 1), date(2026, 2, 28)))
    pl = profit_and_loss(conn, cid, "2026-02-01", "2026-02-28", periods=periods)
    net = pl.lines[-1].amount
    assert tuple(net) == (215_000, 0)
    assert difference(net) == 215_000
    assert percent(net) is None  # nothing in January to compare with
