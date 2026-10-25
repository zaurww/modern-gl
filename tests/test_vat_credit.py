"""The credit of input ƏDV (docs/REPORTING.md, «Модуль ƏDV»): an e-qaimə is credited when
it exists and its amount and its ƏDV are paid, in the share paid, on the day of the later
payment; a customs declaration — as its ƏDV is paid to the customs. The rule has versions
by date. Every figure is worked out by hand in the test's docstring."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.application.vat import (
    CreditEvent,
    CreditRule,
    InvoiceFacts,
    credit_events,
    purchase_facts,
    rule_for,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.vat import vat_credit
from tests.test_invoices import firm as invoice_firm  # noqa: F401 — Альфа, 60, 19, 51, 54

RULE = CreditRule("2024-01-01")


def post(ledger, cid, day: str, *lines: PostingInput) -> int:
    return ledger.post_new(cid, day, list(lines))


def buy(ledger, cid, acc, v, day: str, amount: str, vat: str, number: str) -> int:
    """A purchase of a service from Альфа on an e-qaimə: Dt 26 / Kt 60 and Dt 19 / Kt 60."""
    alfa = (v["Альфа"], v["Д-1"])
    return post(
        ledger,
        cid,
        day,
        PostingInput(acc["26"], acc["60"], amount, (v["Аренда"],), alfa, invoice=number),
        PostingInput(acc["19"], acc["60"], vat, (v["Альфа"],), alfa, invoice=number),
    )


def pay(ledger, cid, acc, v, day: str, amount: str, number: str, deposit: bool = False) -> int:
    """Dt 60 / Kt 51 — the amount from the bank; Kt 54 — the ƏDV from the deposit (D41)."""
    source = acc["54"] if deposit else acc["51"]
    return post(
        ledger,
        cid,
        day,
        PostingInput(
            acc["60"], source, amount, (v["Альфа"], v["Д-1"]), (v["Kapital"],), invoice=number
        ),
    )


def events(conn, cid, number: str, kind: str = "", date_to: str = "2026-12-31") -> list[tuple]:
    facts = {(f.kind, f.invoice): f for f in purchase_facts(conn, cid, date_to)}
    return [(e.day, e.amount) for e in credit_events(facts[(kind, number)], RULE)]


def test_the_rule_is_chosen_by_the_day_and_unknown_years_are_refused():
    assert rule_for("2026-03-31") == RULE
    assert rule_for("2024-01-01") == RULE
    with pytest.raises(ValidationError, match="правил ƏDV за 2023 год в программе нет"):
        rule_for("2023-12-31")


def test_credit_grows_with_the_share_paid(invoice_firm):  # noqa: F811
    """E-qaimə of 05.03: 1 000.00 + ƏDV 180.00.
      20.03  500.00 of the amount from the bank: the share paid is 1/2, but no ƏDV paid — 0.
      25.03  ƏDV 180.00 from the deposit: 180 paid, the share of the amount is 90 — credit 90.
      02.04  the other 500.00: the share is now whole — the other 90.
    The facts: amount 1 000, ƏDV 180, payments by day."""
    conn, ledger, cid, acc, v = invoice_firm
    doc = buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-20", "500", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-25", "180", "MT2603001", deposit=True)
    pay(ledger, cid, acc, v, "2026-04-02", "500", "MT2603001")

    (facts,) = purchase_facts(conn, cid, "2026-04-30")
    assert (facts.invoice, facts.doc_date, facts.document_id) == ("MT2603001", "2026-03-05", doc)
    assert (facts.amount, facts.vat, facts.counterparty_id) == (100_000, 18_000, v["Альфа"])
    assert [(p.day, p.main, p.vat) for p in facts.payments] == [
        ("2026-03-20", 50_000, 0),
        ("2026-03-25", 0, 18_000),
        ("2026-04-02", 50_000, 0),
    ]
    assert events(conn, cid, "MT2603001") == [("2026-03-25", 9_000), ("2026-04-02", 9_000)]
    # up to the end of March only the first event is known
    assert events(conn, cid, "MT2603001", date_to="2026-03-31") == [("2026-03-25", 9_000)]


def test_an_advance_waits_for_the_eqaime(invoice_firm):  # noqa: F811
    """Paid in full on 01.03 — 1 000.00 from the bank, ƏDV 180.00 from the deposit — on an
    e-qaimə that comes on 05.03: the whole 180.00 is credited on 05.03, not on 01.03."""
    conn, ledger, cid, acc, v = invoice_firm
    pay(ledger, cid, acc, v, "2026-03-01", "1000", "MT2603002")
    pay(ledger, cid, acc, v, "2026-03-01", "180", "MT2603002", deposit=True)
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603002")
    assert events(conn, cid, "MT2603002") == [("2026-03-05", 18_000)]


def test_one_side_paid_gives_nothing(invoice_firm):  # noqa: F811
    """Only the amount paid (1 000.00 on 10.03), or only the ƏDV (180.00 on 12.03 for
    another e-qaimə): nothing is credited; the ƏDV alone paid in full counts for 0 while
    the share of the amount paid is 0."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603003")
    pay(ledger, cid, acc, v, "2026-03-10", "1000", "MT2603003")
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603004")
    pay(ledger, cid, acc, v, "2026-03-12", "180", "MT2603004", deposit=True)
    assert events(conn, cid, "MT2603003") == []
    assert events(conn, cid, "MT2603004") == []


def test_the_share_is_rounded_and_the_last_payment_completes_it(invoice_firm):  # noqa: F811
    """E-qaimə 333.33 + ƏDV 60.00; ƏDV paid in full on 06.03; the amount in three parts:
      10.03  111.11 → share 60 × 111.11 / 333.33 = 20.0002 → 20.00
      20.03  111.11 → 60 × 222.22 / 333.33 = 40.0004 → 40.00: +20.00
      30.03  111.11 → 60.00: +20.00
    Overpaying (+1.00 on 31.03) adds nothing: the credit never exceeds the ƏDV."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "333.33", "60", "MT2603005")
    pay(ledger, cid, acc, v, "2026-03-06", "60", "MT2603005", deposit=True)
    for day in ("2026-03-10", "2026-03-20", "2026-03-30"):
        pay(ledger, cid, acc, v, day, "111.11", "MT2603005")
    pay(ledger, cid, acc, v, "2026-03-31", "1", "MT2603005")
    assert events(conn, cid, "MT2603005") == [
        ("2026-03-10", 2_000),
        ("2026-03-20", 2_000),
        ("2026-03-30", 2_000),
    ]


def test_without_partial_share_the_credit_comes_at_once(invoice_firm):  # noqa: F811
    """The same e-qaimə under a version without partial credit: 60.00 on 30.03, when
    everything is paid."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "333.33", "60", "MT2603005")
    pay(ledger, cid, acc, v, "2026-03-06", "60", "MT2603005", deposit=True)
    for day in ("2026-03-10", "2026-03-20", "2026-03-30"):
        pay(ledger, cid, acc, v, day, "111.11", "MT2603005")
    (facts,) = purchase_facts(conn, cid, "2026-03-31")
    whole = CreditRule("2024-01-01", partial_share=False)
    assert credit_events(facts, whole) == [CreditEvent("2026-03-30", 6_000)]


def test_a_customs_declaration_is_credited_as_its_vat_is_paid(invoice_firm):  # noqa: F811
    """Import on declaration 12345 of 10.03: Dt 26 / Kt 60 [Альфа] 2 000.00 — the goods
    (an expense here, stock needs the warehouse), not paid; ƏDV Dt 19 / Kt 76 [Бета, the
    customs] 360.00. Paid to the customs from the bank: 100.00 on 12.03, 260.00 on 15.03 —
    credited 100.00 and 260.00 on those days,
    the goods unpaid. A payment to the supplier is the amount, not the ƏDV."""
    conn, ledger, cid, acc, v = invoice_firm
    alfa, customs = (v["Альфа"], v["Д-1"]), (v["Бета"], v["Общий"])
    post(
        ledger,
        cid,
        "2026-03-10",
        PostingInput(
            acc["26"],
            acc["60"],
            "2000",
            (v["Аренда"],),
            alfa,
            invoice="12345",
            invoice_kind="customs",
        ),
        PostingInput(
            acc["19"],
            acc["76"],
            "360",
            (v["Бета"],),
            customs,
            invoice="12345",
            invoice_kind="customs",
        ),
    )
    for day, amount in (("2026-03-12", "100"), ("2026-03-15", "260")):
        post(
            ledger,
            cid,
            day,
            PostingInput(
                acc["76"],
                acc["51"],
                amount,
                customs,
                (v["Kapital"],),
                invoice="12345",
                invoice_kind="customs",
            ),
        )
    post(
        ledger,
        cid,
        "2026-03-20",
        PostingInput(
            acc["60"],
            acc["51"],
            "500",
            alfa,
            (v["Kapital"],),
            invoice="12345",
            invoice_kind="customs",
        ),
    )
    (facts,) = purchase_facts(conn, cid, "2026-03-31")
    assert (facts.kind, facts.amount, facts.vat) == ("customs", 200_000, 36_000)
    assert [(p.day, p.main, p.vat) for p in facts.payments] == [
        ("2026-03-12", 0, 10_000),
        ("2026-03-15", 0, 26_000),
        ("2026-03-20", 50_000, 0),
    ]
    assert events(conn, cid, "12345", kind="customs") == [
        ("2026-03-12", 10_000),
        ("2026-03-15", 26_000),
    ]


def test_sales_and_eqaime_without_vat_are_not_purchases(invoice_firm):  # noqa: F811
    """A sale (Dt 62 / Kt 46, Dt 46 / Kt 68.2) and a purchase without ƏDV are no input ƏDV."""
    conn, ledger, cid, acc, v = invoice_firm
    beta = (v["Бета"], v["Общий"])
    post(
        ledger,
        cid,
        "2026-03-10",
        PostingInput(acc["62"], acc["46"], "1180", beta, (), invoice="MT2603777"),
        PostingInput(acc["46"], acc["68.2"], "180", (), (), invoice="MT2603777"),
    )
    post(
        ledger,
        cid,
        "2026-03-11",
        PostingInput(
            acc["26"], acc["60"], "400", (v["Аренда"],), (v["Альфа"], v["Д-1"]), invoice="MT2603008"
        ),
    )
    assert purchase_facts(conn, cid, "2026-03-31") == []


def test_the_report_of_a_month_sums_the_credit_and_what_waits(invoice_firm):  # noqa: F811
    """March: e-qaimə A (1 000 + 180) — 90.00 credited on 25.03, 90.00 waits; e-qaimə B
    (500 + 90) paid in full on 28.03 — 90.00; the declaration — 360.00 on 12.03. April: the
    other 90.00 of A on 02.04. Rows carry the counterparty's name; the footer the totals."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-20", "500", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-25", "180", "MT2603001", deposit=True)
    pay(ledger, cid, acc, v, "2026-04-02", "500", "MT2603001")
    buy(ledger, cid, acc, v, "2026-03-07", "500", "90", "MT2603009")
    pay(ledger, cid, acc, v, "2026-03-28", "500", "MT2603009")
    pay(ledger, cid, acc, v, "2026-03-28", "90", "MT2603009", deposit=True)
    customs = (v["Бета"], v["Общий"])
    post(
        ledger,
        cid,
        "2026-03-10",
        PostingInput(
            acc["19"],
            acc["76"],
            "360",
            (v["Бета"],),
            customs,
            invoice="12345",
            invoice_kind="customs",
        ),
    )
    post(
        ledger,
        cid,
        "2026-03-12",
        PostingInput(
            acc["76"],
            acc["51"],
            "360",
            customs,
            (v["Kapital"],),
            invoice="12345",
            invoice_kind="customs",
        ),
    )

    march = vat_credit(conn, cid, "2026-03-01", "2026-03-31")
    assert [
        (r.day, r.invoice, r.counterparty, r.vat, r.credited, r.before, r.waiting)
        for r in march.rows
    ] == [
        ("2026-03-12", "12345", "Бета", 36_000, 36_000, 0, 0),
        ("2026-03-25", "MT2603001", "Альфа", 18_000, 9_000, 0, 9_000),
        ("2026-03-28", "MT2603009", "Альфа", 9_000, 9_000, 0, 0),
    ]
    assert (march.credited, march.waiting, march.waiting_count) == (54_000, 9_000, 1)
    assert march.rows[0].kind == "customs" and march.rows[1].kind == ""

    april = vat_credit(conn, cid, "2026-04-01", "2026-04-30")
    assert [(r.day, r.invoice, r.credited, r.before, r.waiting) for r in april.rows] == [
        ("2026-04-02", "MT2603001", 9_000, 9_000, 0)
    ]
    assert (april.credited, april.waiting, april.waiting_count) == (9_000, 0, 0)

    with pytest.raises(ValidationError, match="за 2023 год"):
        vat_credit(conn, cid, "2023-03-01", "2023-03-31")


def test_facts_of_a_number_without_payments():
    facts = InvoiceFacts("", "MT1", "2026-03-05", amount=100_000, vat=18_000)
    assert credit_events(facts, RULE) == []


def test_the_page_shows_the_credit_of_the_month(invoice_firm, qtbot):  # noqa: F811
    """The page of March: the rows of the report, the footer with the totals; a double
    click on a row opens the e-qaimə's document."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, VatCreditPage
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    doc = buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-20", "1000", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-25", "180", "MT2603001", deposit=True)
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatCreditPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    assert page.title() == "ƏDV к зачёту"
    assert [r.invoice for r in page.model.rows] == ["MT2603001"]
    assert page.model.data(page.model.index(0, 0)) == "25.03.2026"
    assert "К зачёту за период: 180.00" in page.footer.text()
    opened = []
    page.open_document.connect(opened.append)
    page.drill(page.model.rows[0])
    assert opened == [doc]
    page.period.set_period(date(2026, 4, 1), date(2026, 4, 30))
    page.refresh()
    assert page.model.rows == [] and page.stack.currentWidget() is page.empty
