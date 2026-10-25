"""The ƏDV a sale owes (Tax Code 166, 2024 edition; the user's practice, D-new1): each
payment received is a taxable transaction, an advance too; what is owed up to a day is
the larger of the ƏDV received on the deposit account and the ƏDV of the value received.
Every figure is worked out by hand in the test's docstring."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from modern_gl.application.vat import SaleFacts, liability_events, sale_facts
from modern_gl.application.vat.facts import Payment
from modern_gl.application.vat.liability import owed
from modern_gl.application.vat.rules import LiabilityRule
from modern_gl.reporting.vat_liability import vat_liability
from tests.test_invoices import firm as invoice_firm  # noqa: F401 — Альфа, Бета, 51, 54, 62
from tests.test_vat_credit import post

RULE = LiabilityRule("2024-01-01")


def sell(ledger, cid, acc, v, day: str, total: str, vat: str, number: str) -> int:
    """A sale to Бета: Dt 62 / Kt 46 with ƏDV, its ƏDV Dt 46 / Kt 68.2."""
    beta = (v["Бета"], v["Общий"])
    return post(
        ledger,
        cid,
        day,
        PostingInput(acc["62"], acc["46"], total, beta, (), invoice=number),
        PostingInput(acc["46"], acc["68.2"], vat, (), (), invoice=number),
    )


def receive(ledger, cid, acc, v, day: str, amount: str, number: str | None, deposit=False):
    """Dt 51 / Kt 62 — the value to the bank; Dt 54 / Kt 62 — the ƏDV to the deposit."""
    money = acc["54"] if deposit else acc["51"]
    beta = (v["Бета"], v["Общий"])
    return post(
        ledger,
        cid,
        day,
        PostingInput(money, acc["62"], amount, (v["Kapital"],), beta, invoice=number),
    )


def test_the_users_examples_and_an_advance(invoice_firm):  # noqa: F811
    """1) E-qaimə MS01 of 15.01: 100 + ƏDV 18. On 20.01 Бета pays 100 and ƏDV 14 —
          owed max(14; 18 × 100/100 = 18) = 18. On 05.02 the ƏDV 3 more — max(17; 18) = 18:
          nothing more, a row of 0.
    2) E-qaimə MS02 of 15.01: 100 + 18. On 20.01 only ƏDV 10 — max(10; 0) = 10. On 10.02
          the 100 — max(10; 18) = 18: 8 more.
    3) On 25.01 an advance of 200 without a number — 18% of it, 36.
    January owes 18 + 10 + 36 = 64; February 0 + 8 = 8."""
    conn, ledger, cid, acc, v = invoice_firm
    sell(ledger, cid, acc, v, "2026-01-15", "118", "18", "MS01")
    receive(ledger, cid, acc, v, "2026-01-20", "100", "MS01")
    receive(ledger, cid, acc, v, "2026-01-20", "14", "MS01", deposit=True)
    receive(ledger, cid, acc, v, "2026-02-05", "3", "MS01", deposit=True)
    sell(ledger, cid, acc, v, "2026-01-15", "118", "18", "MS02")
    receive(ledger, cid, acc, v, "2026-01-20", "10", "MS02", deposit=True)
    receive(ledger, cid, acc, v, "2026-02-10", "100", "MS02")
    receive(ledger, cid, acc, v, "2026-01-25", "200", None)

    facts = {f.invoice: f for f in sale_facts(conn, cid, "2026-02-28")}
    one = facts["MS01"]
    assert (one.doc_date, one.amount, one.vat, one.counterparty_id) == (
        "2026-01-15",
        10_000,
        1_800,
        v["Бета"],
    )
    assert [(p.day, p.main, p.vat) for p in one.receipts] == [
        ("2026-01-20", 10_000, 1_400),
        ("2026-02-05", 0, 300),
    ]
    assert [(e.day, e.amount) for e in liability_events(one)] == [
        ("2026-01-20", 1_800),
        ("2026-02-05", 0),
    ]
    assert [(e.day, e.amount) for e in liability_events(facts["MS02"])] == [
        ("2026-01-20", 1_000),
        ("2026-02-10", 800),
    ]
    assert facts[None].counterparty_id == v["Бета"]
    assert [(e.day, e.amount) for e in liability_events(facts[None])] == [("2026-01-25", 3_600)]

    january = vat_liability(conn, cid, "2026-01-01", "2026-01-31")
    assert [(r.day, r.invoice, r.counterparty, r.main, r.vat, r.owed) for r in january.rows] == [
        ("2026-01-20", "MS01", "Бета", 10_000, 1_400, 1_800),
        ("2026-01-20", "MS02", "Бета", 0, 1_000, 1_000),
        ("2026-01-25", None, "Бета", 20_000, 0, 3_600),
    ]
    assert january.owed == 6_400
    february = vat_liability(conn, cid, "2026-02-01", "2026-02-28")
    assert [(r.invoice, r.owed) for r in february.rows] == [("MS01", 0), ("MS02", 800)]
    assert february.owed == 800


def test_what_is_owed_by_the_eqaime_and_before_it():
    """Before the e-qaimə: 18% of the value (333.33 → 60.00 rounded), or the ƏDV received
    if more. With it (1 000 + 180): the share of the value (400 → 72), no more than its
    ƏDV even if more came (200 → 180); without ƏDV (500 + 0) — nothing. Money returned
    beyond what came — nothing, not less than nothing."""
    advance = SaleFacts(None, None)
    assert owed(advance, "2026-01-10", 33_333, 0, RULE) == 6_000
    assert owed(advance, "2026-01-10", 10_000, 2_000, RULE) == 2_000
    assert owed(advance, "2026-01-10", -5_000, 0, RULE) == 0
    sale = SaleFacts(None, "MS1", "2026-01-05", 100_000, 18_000)
    assert owed(sale, "2026-01-04", 40_000, 0, RULE) == 7_200  # before its day: 18%
    assert owed(sale, "2026-01-10", 40_000, 0, RULE) == 7_200
    assert owed(sale, "2026-01-10", 0, 20_000, RULE) == 18_000
    free = SaleFacts(None, "MS2", "2026-01-05", 50_000, 0)
    assert owed(free, "2026-01-10", 50_000, 0, RULE) == 0


def test_an_advance_with_a_number_becomes_the_eqaimes_share(invoice_firm):  # noqa: F811
    """An advance of 100 on 10.01 naming MS03 before its e-qaimə: 18% — 18. The e-qaimə of
    20.01 has no ƏDV (500 + 0): on its day nothing is owed, −18 (a correction)."""
    conn, ledger, cid, acc, v = invoice_firm
    receive(ledger, cid, acc, v, "2026-01-10", "100", "MS03")
    post(
        ledger,
        cid,
        "2026-01-20",
        PostingInput(acc["62"], acc["46"], "500", (v["Бета"], v["Общий"]), (), invoice="MS03"),
    )
    (facts,) = sale_facts(conn, cid, "2026-01-31")
    assert [(e.day, e.amount) for e in liability_events(facts)] == [
        ("2026-01-10", 1_800),
        ("2026-01-20", -1_800),
    ]
    assert [Payment("2026-01-10", 10_000, 0)] == facts.receipts


def test_the_page_shows_what_the_month_owes(invoice_firm, qtbot):  # noqa: F811
    """January: an advance of 200 from Бета on 25.01 — 36.00; the row says «аванс», the
    footer the total. February has nothing."""
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, VatLiabilityPage
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    receive(ledger, cid, acc, v, "2026-01-25", "200", None)
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatLiabilityPage(session, ReportParams(date(2026, 1, 1), date(2026, 1, 31)))
    qtbot.addWidget(page)
    model = page.model
    assert page.title() == "ƏDV продаж к уплате"
    assert [model.data(model.index(0, c)) for c in (0, 1, 2)] == ["25.01.2026", "аванс", "Бета"]
    assert "ƏDV продаж за период: 36.00" in page.footer.text()
    page.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    page.refresh()
    assert model.rows == [] and page.stack.currentWidget() is page.empty
