"""Движение денежных средств (D100), direct method, on the company of test_statements.

Money accounts: 50 (cash) and 51 (bank). Their postings:
   1 15.01  Dt 51  Kt 80      10 000   financing: capital
   3 25.01  Dt 60  Kt 51         500   operating: to a supplier
   7 12.02  Dt 51  Kt 62       1 000   operating: from a customer
  10 25.02  Dt 50  Kt 91.1        50   operating: other income
January–February: operating 1 000 − 500 + 50 = 550, financing 10 000; change 10 550;
money 0 → 10 550 (cash 50 + bank 10 500). February alone: 9 500 → 10 550, operating 1 050."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.cash_flow import cash_flow
from tests.test_statements import books, code, shown, window

__all__ = ["books", "window"]  # the fixtures


def test_two_months_of_money(books):
    conn, cid = books
    flow = cash_flow(conn, cid, "2026-01-01", "2026-02-28")
    assert shown(flow) == [
        ("Деньги на начало периода", 0),
        ("Операционная деятельность", None),
        ("Покупатели и заказчики", 100_000),
        ("Поставщики и подрядчики", -50_000),
        ("Прочие доходы", 5_000),
        ("Чистый поток от операционной деятельности", 55_000),
        ("Финансовая деятельность", None),
        ("Уставный капитал", 1_000_000),
        ("Чистый поток от финансовой деятельности", 1_000_000),
        ("Изменение денег за период", 1_055_000),
        ("Деньги на конец периода", 1_055_000),
    ]
    assert flow.unbalanced == 0


def test_february_starts_with_januarys_money_and_transfers_are_no_flow(books, ledger):
    conn, cid = books
    code = {
        r["code"]: r["id"]
        for r in conn.execute("SELECT id, code FROM accounts WHERE company_id = ?", (cid,))
    }
    ledger.post_new(cid, "2026-02-26", [PostingInput(code["50"], code["51"], "200")])
    flow = cash_flow(conn, cid, "2026-02-01", "2026-02-28")
    figures = dict(shown(flow))
    assert figures["Деньги на начало периода"] == 950_000
    assert figures["Чистый поток от операционной деятельности"] == 105_000
    assert "Финансовая деятельность" not in figures
    assert figures["Деньги на конец периода"] == 1_055_000
    assert flow.unbalanced == 0


def test_a_fee_paid_straight_to_the_result_is_operating(books, ledger):
    """The short chart writes a bank fee as Dt 80 (or 99) Kt 51: money spent working, not
    financing (D102). February: 1 050 operating as above, minus the fee 7 → 1 043."""
    conn, cid = books
    code = {
        r["code"]: r["id"]
        for r in conn.execute("SELECT id, code FROM accounts WHERE company_id = ?", (cid,))
    }
    ledger.post_new(cid, "2026-02-27", [PostingInput(code["99"], code["51"], "7")])
    figures = dict(shown(cash_flow(conn, cid, "2026-02-01", "2026-02-28")))
    assert figures["Финансовый результат"] == -700
    assert figures["Чистый поток от операционной деятельности"] == 104_300
    assert "Финансовая деятельность" not in figures


def test_a_flow_opens_into_the_other_accounts(books):
    from modern_gl.reporting.statements import ACCOUNTS

    conn, cid = books
    flow = cash_flow(conn, cid, "2026-01-01", "2026-02-28", detail=ACCOUNTS)
    rows = [(ln.kind, code(ln), ln.amount) for ln in flow.lines]
    customers = rows.index(("line", "Покупатели и заказчики", 100_000))
    assert rows[customers + 1] == ("account", "62", 100_000)
    capital = rows.index(("line", "Уставный капитал", 1_000_000))
    assert rows[capital + 1] == ("account", "80", 1_000_000)
    assert flow.unbalanced == 0


def test_the_page_shows_the_cash_flow(window, qtbot):
    from modern_gl.desktop.reports_page import StatementsPage

    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    page.cash_button.click()
    qtbot.waitUntil(lambda: page.model.rows[0].title == "Деньги на начало периода")
    assert page.model.rows[-1].title == "Деньги на конец периода"
    assert page.footer.text().startswith("Остаток денег сходится")


def test_every_title_of_the_cash_flow_has_azerbaijani_translation():
    from modern_gl.i18n_az import AZ
    from modern_gl.reporting.cash_flow import ACTIVITIES

    titles = {t for pair in ACTIVITIES for t in pair}
    titles |= {"Деньги на начало периода", "Изменение денег за период", "Деньги на конец периода"}
    assert sorted(t for t in titles if t not in AZ) == []
