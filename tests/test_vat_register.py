"""«Реестр e-qaimə» for the ƏDV declaration (docs/REPORTING.md, «Этапы до декларации ƏDV»,
stage 1): purchases and sales of a month apart, by the day of the e-qaimə; amount, ƏDV,
total, unpaid at the month's end; totals by rate. Figures worked out by hand."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.vat_register import (
    BOOKS_CHANGED,
    NOT_RECONCILED,
    PORTAL_CHANGED,
    RECONCILED,
    RateTotal,
    RegisterRow,
    rate_totals,
    vat_register,
)
from tests.helpers.eqaime_reconciliation import on_portal
from tests.helpers.vat_credit import buy, pay, post


def sell(ledger, cid, acc, v, day: str, total: str, vat: str, number: str) -> int:
    """A sale to Бета: Dt 62 / Kt 46 with ƏDV, its ƏDV Dt 46 / Kt 68.2."""
    lines = [PostingInput(acc["62"], acc["46"], total, (v["Бета"], v["Общий"]), (), invoice=number)]
    if vat != "0":
        lines.append(PostingInput(acc["46"], acc["68.2"], vat, (), (), invoice=number))
    return post(ledger, cid, day, *lines)


def test_the_register_of_a_month(invoice_firm):
    """March, purchases:
      MT2603001 05.03 Альфа 1 000 + 180; paid 500 (20.03) and ƏДV 180 (25.03) → unpaid
                1 180 − 680 = 500; the other 500 paid on 02.04 is April's — still 500.
      MT2603009 07.03 Альфа 500 + 90, paid in full on 28.03; corrected on 10.04 — red
                storno of 500 + 90, then 400 + 72 anew → March shows 472 (a correction is
                the period of its e-qaimə, not April's); unpaid at 31.03 → 0.
      12345     10.03 declaration: goods Альфа 2 000 (Kt 60, unpaid), ƏDV 360 to the customs
                (Kt 76 Бета) paid 12.03 → 2 000 + 360, unpaid 2 000.
      MT2603008 11.03 Альфа 400 without ƏDV → unpaid 400.
      MT2602001 25.02 and MT2604001 02.04 — other months, not in March.
    Sales: MT2603777 10.03 Бета 1 180 with ƏDV 180 → 1 000 + 180; Бета paid 1 000 on
      15.03 → unpaid 180. MT2603778 12.03 Бета 300 without ƏDV → unpaid 300.
    By rate — purchases 18%: 3 e-qaimə, 1 000 + 400 + 2 000 = 3 400, ƏDV 180 + 72 + 360 =
      612; without ƏDV: 1, 400. Sales 18%: 1, 1 000, 180; without: 1, 300."""
    conn, ledger, cid, acc, v = invoice_firm
    alfa, customs = (v["Альфа"], v["Д-1"]), (v["Бета"], v["Общий"])
    buy(ledger, cid, acc, v, "2026-02-25", "100", "18", "MT2602001")
    doc_a = buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-20", "500", "MT2603001")
    pay(ledger, cid, acc, v, "2026-03-25", "180", "MT2603001", deposit=True)
    pay(ledger, cid, acc, v, "2026-04-02", "500", "MT2603001")
    doc_b = buy(ledger, cid, acc, v, "2026-03-07", "500", "90", "MT2603009")
    pay(ledger, cid, acc, v, "2026-03-28", "500", "MT2603009")
    pay(ledger, cid, acc, v, "2026-03-28", "90", "MT2603009", deposit=True)
    doc_c = post(
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
    post(
        ledger,
        cid,
        "2026-03-11",
        PostingInput(acc["26"], acc["60"], "400", (v["Аренда"],), alfa, invoice="MT2603008"),
    )
    buy(ledger, cid, acc, v, "2026-04-02", "200", "36", "MT2604001")
    ledger.reverse(cid, doc_b, "2026-04-10")  # March closed: red storno, then anew
    buy(ledger, cid, acc, v, "2026-04-10", "400", "72", "MT2603009")
    doc_s = sell(ledger, cid, acc, v, "2026-03-10", "1180", "180", "MT2603777")
    post(
        ledger,
        cid,
        "2026-03-15",
        PostingInput(acc["51"], acc["62"], "1000", (v["Kapital"],), customs, invoice="MT2603777"),
    )
    sell(ledger, cid, acc, v, "2026-03-12", "300", "0", "MT2603778")

    march = vat_register(conn, cid, "2026-03-01", "2026-03-31")
    assert [
        (
            r.doc_date,
            r.kind,
            r.invoice,
            r.counterparty,
            r.tax_id,
            r.amount,
            r.vat,
            r.total,
            r.unpaid,
        )
        for r in march.purchases
    ] == [
        ("2026-03-05", "", "MT2603001", "Альфа", "1234567890", 100_000, 18_000, 118_000, 50_000),
        ("2026-03-07", "", "MT2603009", "Альфа", "1234567890", 40_000, 7_200, 47_200, 0),
        (
            "2026-03-10",
            "customs",
            "12345",
            "Альфа",
            "1234567890",
            200_000,
            36_000,
            236_000,
            200_000,
        ),
        ("2026-03-11", "", "MT2603008", "Альфа", "1234567890", 40_000, 0, 40_000, 40_000),
    ]
    assert (march.purchases[0].document_id, march.purchases[2].document_id) == (doc_a, doc_c)
    assert [(r.invoice, r.counterparty, r.amount, r.vat, r.unpaid) for r in march.sales] == [
        ("MT2603777", "Бета", 100_000, 18_000, 18_000),
        ("MT2603778", "Бета", 30_000, 0, 30_000),
    ]
    assert march.sales[0].document_id == doc_s
    assert march.purchase_rates == [
        RateTotal(18, 3, 340_000, 61_200),
        RateTotal(None, 1, 40_000, 0),
    ]
    assert march.sale_rates == [RateTotal(18, 1, 100_000, 18_000), RateTotal(None, 1, 30_000, 0)]

    april = vat_register(conn, cid, "2026-04-01", "2026-04-30")
    assert [(r.invoice, r.amount, r.vat, r.unpaid) for r in april.purchases] == [
        ("MT2604001", 20_000, 3_600, 23_600)
    ]
    assert april.sales == []


def checks(conn, cid, date_from: str, date_to: str) -> list[tuple]:
    report = vat_register(conn, cid, date_from, date_to)
    return [(c.state, c.numbers) for c in report.checks]


def test_the_register_knows_whether_its_month_agrees_with_the_portal(invoice_firm):
    """March: purchase MT2603001 (1 000 + 180), sale MT2603777. Nothing marked — both
    «не сверено». Purchases marked in two halves (01–15, 16–31) cover March; sales the
    month. On 10.04 the purchase is corrected (storno and 400 + 72 anew, D140): the books
    of the first half changed after its mark — «книга изменилась». Marked again — agrees.
    The sale changes on the portal on 20.04, after its mark — «изменилось на портале»
    with its number. April is not marked at all."""
    conn, ledger, cid, acc, v = invoice_firm
    doc = buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    sell(ledger, cid, acc, v, "2026-03-10", "1180", "180", "MT2603777")
    march = ("2026-03-01", "2026-03-31")
    assert checks(conn, cid, *march) == [(NOT_RECONCILED, ()), (NOT_RECONCILED, ())]

    ledger.eqaime.mark_reconciled(cid, False, "2026-03-01", "2026-03-15", "2026-04-01T09:00:00")
    assert checks(conn, cid, *march)[0] == (NOT_RECONCILED, ())  # half of March
    ledger.eqaime.mark_reconciled(cid, False, "2026-03-16", "2026-03-31", "2026-04-01T09:00:00")
    sale = on_portal("MT2603777", "2026-03-10", 118_000, 18_000, outgoing=True)
    ledger.eqaime.remember_portal(cid, [sale], "2026-04-01T09:00:00")
    ledger.eqaime.mark_reconciled(cid, True, *march, "2026-04-01T10:00:00")
    assert checks(conn, cid, *march) == [(RECONCILED, ()), (RECONCILED, ())]

    ledger.reverse(cid, doc, "2026-04-10")
    buy(ledger, cid, acc, v, "2026-04-10", "400", "72", "MT2603001")
    assert checks(conn, cid, *march)[0] == (BOOKS_CHANGED, ())
    ledger.eqaime.mark_reconciled(cid, False, "2026-03-01", "2026-03-15", "2026-04-11T09:00:00")
    assert checks(conn, cid, *march)[0] == (RECONCILED, ())

    changed = on_portal("MT2603777", "2026-03-10", 118_000, 18_000, "canceled", outgoing=True)
    ledger.eqaime.remember_portal(cid, [changed], "2026-04-20T09:00:00")
    assert checks(conn, cid, *march)[1] == (PORTAL_CHANGED, ("MT2603777",))
    assert checks(conn, cid, "2026-04-01", "2026-04-30") == [
        (NOT_RECONCILED, ()),
        (NOT_RECONCILED, ()),
    ]


def test_the_rate_is_whole_percent_of_the_amount():
    """333.33 + 60.00: 60 / 333.33 = 18.0002% → 18; 100.00 + 10.00 → 10; ƏДV 0 → none.
    Totals: 18% first, then 10%, without ƏDV last."""

    def row(amount: int, vat: int) -> RegisterRow:
        return RegisterRow("", "X", "2026-03-01", "", "", amount, vat, 0, None)

    rows = [row(10_000, 0), row(10_000, 1_000), row(33_333, 6_000)]
    assert [r.rate for r in rows] == [None, 10, 18]
    assert rate_totals(rows) == [
        RateTotal(18, 1, 33_333, 6_000),
        RateTotal(10, 1, 10_000, 1_000),
        RateTotal(None, 1, 10_000, 0),
    ]


def test_the_page_shows_purchases_then_sales_with_totals(invoice_firm, qtbot):
    """March: one purchase 1 000 + 180 and one sale 1 180 with ƏDV 180. The page: the
    heading «Покупки», the row, «Итого 18%: 1»; the same for sales; the footer — the ƏDV
    of both; a double click on a row opens its document. April is empty."""
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, VatRegisterPage
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    doc = buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    sell(ledger, cid, acc, v, "2026-03-10", "1180", "180", "MT2603777")
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatRegisterPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    model = page.model
    assert page.title() == "Реестр e-qaimə"
    texts = [[model.data(model.index(i, c)) for c in (0, 1, 2)] for i in range(model.rowCount())]
    assert texts == [
        ["Покупки", "", ""],
        ["05.03.2026", "MT2603001", "Альфа"],
        ["", "", "Итого 18%: 1"],
        ["Продажи", "", ""],
        ["10.03.2026", "MT2603777", "Бета"],
        ["", "", "Итого 18%: 1"],
    ]
    assert "Покупки: ƏDV 180.00" in page.footer.text()
    opened = []
    page.open_document.connect(opened.append)
    page.drill(model.rows[1])
    page.drill(model.rows[0])  # a heading opens nothing
    assert opened == [doc]
    page.period.set_period(date(2026, 4, 1), date(2026, 4, 30))
    page.refresh()
    assert model.rows == [] and page.stack.currentWidget() is page.empty


def test_the_page_shows_the_portal_check_and_opens_the_reconciliation(
    invoice_firm,
    qtbot,
    monkeypatch,
):
    """March, purchases marked reconciled, sales not: the footer says so under the
    totals. «⋯ → Сверить продажи с порталом…» opens the reconciliation of sales for March;
    viewing a snapshot (D80) — no such items."""
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import eqaime_reconciliation_page
    from modern_gl.desktop.reports_page import ReportParams, VatRegisterPage
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT2603001")
    ledger.eqaime.mark_reconciled(cid, False, "2026-03-01", "2026-03-31")
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatRegisterPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    footer = page.footer.text()
    assert "Покупки — сверены с порталом" in footer
    assert "продажи — не сверены с порталом" in footer

    opened = []

    class Dialog:
        def __init__(self, session, parent, direction):
            self.period_field = self
            self.chosen_document = None
            opened.append(direction)

        def set_period(self, first, last):
            opened.append((first, last))

        def exec(self):
            return 0

    monkeypatch.setattr(eqaime_reconciliation_page, "EqaimeReconciliationDialog", Dialog)
    items = dict(i for i in page.more_items() if i is not None)
    items["Сверить продажи с порталом…"]()
    assert opened == ["sale", (date(2026, 3, 1), date(2026, 3, 31))]

    session.read_only = True
    assert "Сверить продажи с порталом…" not in dict(i for i in page.more_items() if i)
