"""Прибыли и убытки по IFRS 18 (D128) on the short chart «classic».

Revenue is net of ƏDV; an other income or expense goes to its category by the account on
the other side; the deferred tax is a line of its own and its balance a line of the
long-term liabilities.

    1 05.03  Dt 50            Kt 46             1 180   a sale with ƏDV
    2 05.03  Dt 46            Kt 68.2             180   its ƏDV: revenue 1 000
    3 10.03  Dt 26 [Аренда]   Kt 50               100   operating expense
    4 12.03  Dt 80            Kt 50                 5   a bank fee — other expense, operating
    5 15.03  Dt 80            Kt 60 [EUR, 0]        9   exchange loss on a supplier — operating
    6 20.03  Dt 52 [USD, 0]   Kt 80                12   exchange gain on money — investing
    7 22.03  Dt 80            Kt 57                 7   loss of a conversion — investing
    8 25.03  Dt 80            Kt 90                40   interest on the loan — financing
    9 31.03  Dt 80            Kt 68.3              20   current profit tax
   10 31.03  Dt 80            Kt 77                 3   deferred tax

Gross 1 000; operating: −100 rent, other expenses −5 − 9 = −14 → 886; investing:
exchange differences on money 12 − 7 = 5 → 891 before financing and tax; financing −40 →
851 before tax; taxes −20 and −3 → net 828.
"""

from __future__ import annotations

import pytest

from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.reporting.profit_loss import ACCOUNTS, profit_and_loss
from modern_gl.reporting.statements import balance_sheet


@pytest.fixture
def march(ledger: Ledger):
    cid = ledger.create_company("IFRS 18")
    apply_chart_template(ledger, cid, "classic", "ru")
    codes = ("26", "46", "50", "52", "57", "60", "68.2", "68.3", "77", "80", "90")
    acc = {c: ledger.account_id(cid, c) for c in codes}

    def value(kind: str, name: str, owner: int | None = None) -> int:
        return ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name, None, owner)

    rent = value("cost_item", "Аренда")
    bank = value("counterparty", "Bank")
    loan = value("contract", "Kredit", bank)
    supplier = value("counterparty", "Supplier")
    deal = value("contract", "Müqavilə", supplier)
    account = value("bank_account", "USD hesab")
    usd, eur = ledger.currency_id(cid, "USD"), ledger.currency_id(cid, "EUR")

    def p(dt, ct, amount, dt_sc=(), ct_sc=(), currency=None):
        fx = {} if currency is None else {"currency_id": currency, "currency_amount": 0}
        return PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc, **fx)

    for day, posting in [
        ("2026-03-05", p("50", "46", "1180")),
        ("2026-03-05", p("46", "68.2", "180")),
        ("2026-03-10", p("26", "50", "100", [rent])),
        ("2026-03-12", p("80", "50", "5")),
        ("2026-03-15", p("80", "60", "9", ct_sc=[supplier, deal], currency=eur)),
        ("2026-03-20", p("52", "80", "12", [account], currency=usd)),
        ("2026-03-22", p("80", "57", "7")),
        ("2026-03-25", p("80", "90", "40", ct_sc=[bank, loan])),
        ("2026-03-31", p("80", "68.3", "20")),
        ("2026-03-31", p("80", "77", "3")),
    ]:
        ledger.post_new(cid, day, [posting])
    return ledger.conn, cid


def shown(statement) -> list[tuple[str, int]]:
    return [(ln.title, ln.amount) for ln in statement.lines]


def test_the_categories_of_ifrs_18(march):
    conn, cid = march
    statement = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31")
    assert shown(statement) == [
        ("Выручка", 100_000),
        ("Валовая прибыль", 100_000),
        ("Операционные расходы", -10_000),
        ("Прочие расходы", -1_400),
        ("Операционная прибыль", 88_600),
        ("Курсовые разницы по денежным средствам", 500),
        ("Прибыль до финансирования и налога на прибыль", 89_100),
        ("Финансовые расходы", -4_000),
        ("Прибыль до налогообложения", 85_100),
        ("Налог на прибыль", -2_000),
        ("Отложенный налог на прибыль", -300),
        ("Чистая прибыль (убыток)", 82_800),
    ]


def test_the_vat_of_the_sales_shows_only_in_the_detail(march):
    """By accounts the revenue opens into the gross sales and the ƏDV taken off them."""
    conn, cid = march
    statement = profit_and_loss(conn, cid, "2026-03-01", "2026-03-31", detail=ACCOUNTS)
    start = next(i for i, ln in enumerate(statement.lines) if ln.title == "Выручка")
    revenue = statement.lines[start : start + 3]
    assert [(ln.kind, ln.amount) for ln in revenue] == [
        ("line", 100_000),
        ("account", 118_000),
        ("account", -18_000),
    ]
    assert revenue[1].title.startswith("46")
    assert revenue[2].title == "НДС с продаж"
    assert revenue[2].account_id == Ledger(conn).account_id(cid, "46")
    assert statement.lines[-1].amount == 82_800


def test_without_financing_there_is_no_subtotal_before_it(march):
    """A month with no financing: «before financing and tax» would repeat «before tax»."""
    conn, cid = march
    statement = profit_and_loss(conn, cid, "2026-03-01", "2026-03-22")
    titles = [ln.title for ln in statement.lines]
    assert "Прибыль до финансирования и налога на прибыль" not in titles
    assert statement.lines[-1].amount == 100_000 - 10_000 - 1_400 + 500


def test_the_deferred_tax_is_a_long_term_line_of_the_balance_sheet(march):
    conn, cid = march
    lines = shown(balance_sheet(conn, cid, "2026-03-31"))
    start = next(i for i, (title, _) in enumerate(lines) if title == "Долгосрочные обязательства")
    assert ("Отложенные налоговые обязательства", 300) in lines[start:]


def test_interest_in_the_cash_flow_follows_ias_7(ledger: Ledger):
    """Interest paid is financing, interest received investing (IAS 7 with IFRS 18).

    05.04 Dt 50 Kt 85 1 000 the capital; 10.04 Dt 91 Kt 50 30 interest paid;
    20.04 Dt 50 Kt 92 12 interest received: financing 1 000 − 30 = 970, investing 12."""
    from modern_gl.reporting.cash_flow import cash_flow

    cid = ledger.create_company("IAS 7")
    apply_chart_template(ledger, cid, "classic", "ru")
    cash, capital = ledger.account_id(cid, "50"), ledger.account_id(cid, "85")
    paid = ledger.add_account(cid, "91", "Проценты к уплате", account_type="finance_expense")
    got = ledger.add_account(cid, "92", "Проценты к получению", account_type="finance_income")
    owner = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "Owner")
    ledger.post_new(cid, "2026-04-05", [PostingInput(cash, capital, "1000", (), [owner])])
    ledger.post_new(cid, "2026-04-10", [PostingInput(paid, cash, "30")])
    ledger.post_new(cid, "2026-04-20", [PostingInput(cash, got, "12")])
    lines = shown(cash_flow(ledger.conn, cid, "2026-04-01", "2026-04-30"))
    titles = [title for title, _ in lines]
    investing = titles.index("Инвестиционная деятельность")
    financing = titles.index("Финансовая деятельность")
    assert ("Финансовые доходы", 1_200) in lines[investing:financing]
    assert ("Финансовые расходы", -3_000) in lines[financing:]
    assert ("Чистый поток от финансовой деятельности", 97_000) in lines[financing:]
