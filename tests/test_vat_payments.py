"""«Оплаты поставщикам и e-qaimə»: the money paid to each supplier against their e-qaimə,
the ƏDV credited (D138), an open advance, e-qaimə not paid, and a warning when an e-qaimə
is paid but its ƏDV is not credited. Every figure is worked out by hand in the docstring."""

from __future__ import annotations

from datetime import date

from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.vat import vat_credit
from modern_gl.reporting.vat_payments import vat_payments
from modern_gl.reporting.vat_receipts import warning
from tests.test_invoices import firm as invoice_firm  # noqa: F401 — Альфа, Бета, 51, 54, 60, 61
from tests.test_vat_credit import post
from tests.test_vat_receipts import party


def buy(ledger, cid, acc, v, who: str, day: str, amount: str, vat: str, number: str) -> int:
    """Dt 26 / Kt 60 and Dt 19 / Kt 60 on the e-qaimə."""
    return post(
        ledger,
        cid,
        day,
        PostingInput(acc["26"], acc["60"], amount, (v["Аренда"],), party(v, who), invoice=number),
        PostingInput(acc["19"], acc["60"], vat, (v[who],), party(v, who), invoice=number),
    )


def pay(ledger, cid, acc, v, day: str, amount: str, number=None, to="60", source="51") -> int:
    """Dt 60 (61 — an advance) / Kt 51 (54 — from the ƏDV deposit) to Альфа."""
    line = PostingInput(
        acc[to], acc[source], amount, party(v, "Альфа"), (v["Kapital"],), invoice=number
    )
    return post(ledger, cid, day, line)


def test_suppliers_money_against_their_eqaime(invoice_firm):  # noqa: F811
    """Альфа. MT01 of 05.03, 1 000 + 180: on 10.03 1 000 from the bank and 180 from the
    deposit, both naming it — credited 180, nothing to look at.
    MT02 of 15.03, 500 + 90: paid ahead on 01.03, 590 from the bank to 61 without a number.
    The advance pays MT02 (590 of 590) — its ƏDV of what is paid is 90, credited 0 (the
    credit goes by number): 90 «без номера»; nothing open.
    Бета: MT03 of 20.03, 200 + 36, not paid — 236 unpaid, no warning.
    March credits 180, as «ƏDV к зачёту». On 05.04 the bank sets the advance against MT02
    (Dt 60 / Kt 61 590, naming it): its value is paid by number now (590 ≥ 500), the ƏDV
    still not from the deposit — credited 0, the warning becomes «не на депозит»."""
    conn, ledger, cid, acc, v = invoice_firm
    mt01 = buy(ledger, cid, acc, v, "Альфа", "2026-03-05", "1000", "180", "MT01")
    pay(ledger, cid, acc, v, "2026-03-10", "1000", "MT01")
    pay(ledger, cid, acc, v, "2026-03-10", "180", "MT01", source="54")
    pay(ledger, cid, acc, v, "2026-03-01", "590", to="61")
    buy(ledger, cid, acc, v, "Альфа", "2026-03-15", "500", "90", "MT02")
    buy(ledger, cid, acc, v, "Бета", "2026-03-20", "200", "36", "MT03")

    march = vat_payments(conn, cid, "2026-03-01", "2026-03-31")
    alfa, beta = march.parties
    assert [
        (ln.invoice, ln.by_invoice, ln.no_number, ln.deposit, ln.amount, ln.vat, ln.tax)
        for ln in alfa.lines
    ] == [
        ("MT01", 100_000, 0, 18_000, 100_000, 18_000, 18_000),
        ("MT02", 0, 0, 0, 50_000, 9_000, 0),
        (None, 0, 59_000, 0, 0, 0, 0),
    ]
    assert alfa.lines[0].document_id == mt01
    assert (alfa.advance, alfa.unpaid, alfa.excess) == (0, 0, 9_000)
    assert (
        warning(alfa) == "ƏDV 90.00 не зачтён: оплачено без номера e-qaimə — укажите номер в банке"
    )
    assert [(ln.invoice, ln.amount, ln.vat) for ln in beta.lines] == [("MT03", 20_000, 3_600)]
    assert (beta.advance, beta.unpaid, beta.excess, warning(beta)) == (0, 23_600, 0, None)
    assert (march.total.tax, march.total.unpaid, march.warnings) == (18_000, 23_600, 1)
    assert march.total.tax == vat_credit(conn, cid, "2026-03-01", "2026-03-31").credited

    post(
        ledger,
        cid,
        "2026-04-05",
        PostingInput(
            acc["60"], acc["61"], "590", party(v, "Альфа"), party(v, "Альфа"), invoice="MT02"
        ),
    )
    april = vat_payments(conn, cid, "2026-04-01", "2026-04-30")
    alfa, beta = april.parties
    assert (alfa.lines, alfa.advance, alfa.unpaid, alfa.excess) == ([], 0, 0, 9_000)
    assert warning(alfa) == "ƏDV 90.00 не зачтён: оплачено, но ƏDV не перечислен на депозит"
    assert (beta.unpaid, april.total.tax) == (23_600, 0)


def test_an_open_advance_to_a_supplier(invoice_firm):  # noqa: F811
    """On 01.03 300 to Альфа without a number, no e-qaimə yet: an advance of 300, nothing
    credited, nothing to look at."""
    conn, ledger, cid, acc, v = invoice_firm
    pay(ledger, cid, acc, v, "2026-03-01", "300", to="61")
    (alfa,) = vat_payments(conn, cid, "2026-03-01", "2026-03-31").parties
    assert (alfa.no_number, alfa.advance, alfa.unpaid, alfa.tax, warning(alfa)) == (
        30_000,
        30_000,
        0,
        0,
        None,
    )


def test_the_suppliers_page(invoice_firm, qtbot):  # noqa: F811
    """The page of the suppliers: its title, Альфа with MT01, the footer's credit."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, VatPaymentsPage
    from modern_gl.desktop.reports_page.subconto_analysis import INDENT
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "Альфа", "2026-03-05", "1000", "180", "MT01")
    pay(ledger, cid, acc, v, "2026-03-10", "1000", "MT01")
    pay(ledger, cid, acc, v, "2026-03-10", "180", "MT01", source="54")
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatPaymentsPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    model = page.model
    assert page.title() == "Оплаты поставщикам и e-qaimə"
    assert [model.data(model.index(r, 0)) for r in range(len(model.rows))] == [
        "Альфа",
        INDENT + "MT01",
        "Итого",
    ]
    assert "Зачтено ƏDV за период: 180.00" in page.footer.text()
