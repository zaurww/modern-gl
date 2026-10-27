"""«Поступления и e-qaimə» (REPORTING.md, stage 3a): the money of each buyer against the
e-qaimə issued to them, the ƏDV owed (D142), an open advance, e-qaimə not paid, and a
warning when more ƏDV is owed than the e-qaimə and the advance carry. Every figure is
worked out by hand in the test's docstring."""

from __future__ import annotations

from datetime import date

from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.vat_liability import vat_liability
from modern_gl.reporting.vat_receipts import vat_receipts, warning
from tests.helpers.vat_credit import post
from tests.helpers.vat_receipts import party


def sell(ledger, cid, acc, v, who: str, day: str, total: str, vat: str, number: str) -> int:
    """Dt 62 / Kt 46 with ƏDV; its ƏDV Dt 46 / Kt 68.2 (none when "0")."""
    lines = [PostingInput(acc["62"], acc["46"], total, party(v, who), (), invoice=number)]
    if vat != "0":
        lines.append(PostingInput(acc["46"], acc["68.2"], vat, (), (), invoice=number))
    return post(ledger, cid, day, *lines)


def receive(ledger, cid, acc, v, who: str, day: str, amount: str, number: str | None = None):
    """Dt 51 / Kt 62 — the money to the bank account."""
    line = PostingInput(
        acc["51"], acc["62"], amount, (v["Kapital"],), party(v, who), invoice=number
    )
    return post(ledger, cid, day, line)


def test_buyers_money_against_their_eqaime(invoice_firm):
    """Бета: on 10.01 236 to the bank without a number — the ƏDV came with the value;
    owed 18% × 236 = 42.48. On 20.01 two e-qaimə close it: MS01 and MS02, 100 + 18 each.
    The advance pays both (oldest first): nothing open, ƏDV carried 36; owed 42.48 —
    6.48 too much: «ƏDV пришёл на расчётный счёт?». On 15.02 50 more without a number —
    9 owed, an open advance of 50 carries 18% of it, 9: still 6.48 too much.
    Альфа: on 05.01 100 without a number — 18 owed. On 25.01 MA01 100 without ƏDV, on 28.01
    MA02 200 + 36 = 236. At 31.01 the 100 pays MA01, MA02 is unpaid (236); the ƏDV of what
    is paid is 0, owed 18 — 18 too much, the e-qaimə without ƏDV after an advance. On
    10.02 100 naming MA02: owed 36 × 100/200 = 18; at 28.02 unpaid 236 − 100 = 136,
    carried 18 of MA02, owed 36 — still 18 too much.
    January owes 42.48 + 18 = 60.48, February 9 + 18 = 27 — as «ƏDV продаж к уплате»."""
    conn, ledger, cid, acc, v = invoice_firm
    receive(ledger, cid, acc, v, "Бета", "2026-01-10", "236")
    ms01 = sell(ledger, cid, acc, v, "Бета", "2026-01-20", "118", "18", "MS01")
    sell(ledger, cid, acc, v, "Бета", "2026-01-20", "118", "18", "MS02")
    receive(ledger, cid, acc, v, "Бета", "2026-02-15", "50")
    receive(ledger, cid, acc, v, "Альфа", "2026-01-05", "100")
    sell(ledger, cid, acc, v, "Альфа", "2026-01-25", "100", "0", "MA01")
    sell(ledger, cid, acc, v, "Альфа", "2026-01-28", "236", "36", "MA02")
    receive(ledger, cid, acc, v, "Альфа", "2026-02-10", "100", "MA02")

    january = vat_receipts(conn, cid, "2026-01-01", "2026-01-31")
    alfa, beta = january.parties
    assert (alfa.name, beta.name) == ("Альфа", "Бета")
    assert [
        (ln.invoice, ln.no_number, ln.by_invoice, ln.amount, ln.vat, ln.tax) for ln in beta.lines
    ] == [
        ("MS01", 0, 0, 10_000, 1_800, 0),
        ("MS02", 0, 0, 10_000, 1_800, 0),
        (None, 23_600, 0, 0, 0, 4_248),
    ]
    assert beta.lines[0].document_id == ms01
    assert (beta.no_number, beta.amount, beta.vat, beta.tax) == (23_600, 20_000, 3_600, 4_248)
    assert (beta.advance, beta.unpaid, beta.excess) == (0, 0, 648)
    assert warning(beta) == "ƏDV больше, чем в e-qaimə, на 6.48: ƏDV пришёл на расчётный счёт?"
    assert [(ln.invoice, ln.amount, ln.vat, ln.tax) for ln in alfa.lines] == [
        ("MA01", 10_000, 0, 0),
        ("MA02", 20_000, 3_600, 0),
        (None, 0, 0, 1_800),
    ]
    assert (alfa.advance, alfa.unpaid, alfa.excess) == (0, 23_600, 1_800)
    assert warning(alfa) == "ƏDV начислен с аванса, а e-qaimə без ƏDV: начислено лишнее 18.00"
    total = january.total
    assert (total.tax, total.advance, total.unpaid, january.warnings) == (6_048, 0, 23_600, 2)
    assert total.tax == vat_liability(conn, cid, "2026-01-01", "2026-01-31").owed

    february = vat_receipts(conn, cid, "2026-02-01", "2026-02-28")
    alfa, beta = february.parties
    assert [(ln.invoice, ln.by_invoice, ln.tax) for ln in alfa.lines] == [("MA02", 10_000, 1_800)]
    assert (alfa.advance, alfa.unpaid, alfa.excess) == (0, 13_600, 1_800)
    assert [(ln.invoice, ln.no_number, ln.tax) for ln in beta.lines] == [(None, 5_000, 900)]
    assert (beta.advance, beta.unpaid, beta.excess) == (5_000, 0, 648)
    assert february.total.tax == 2_700
    assert february.total.tax == vat_liability(conn, cid, "2026-02-01", "2026-02-28").owed


def test_money_on_the_deposit_and_an_honest_advance_warn_nothing(invoice_firm):
    """Бета on 10.01: 100 to the bank and 18 to the ƏDV deposit, no number — owed
    max(18; 18% × 100) = 18. MS05 of 20.01, 100 + 18, closes it: carried 18 = owed, no
    warning. A buyer with nothing in the period and nothing open is not shown (Альфа)."""
    conn, ledger, cid, acc, v = invoice_firm
    receive(ledger, cid, acc, v, "Бета", "2026-01-10", "100")
    post(
        ledger,
        cid,
        "2026-01-10",
        PostingInput(acc["54"], acc["62"], "18", (v["Kapital"],), party(v, "Бета")),
    )
    sell(ledger, cid, acc, v, "Бета", "2026-01-20", "118", "18", "MS05")
    (beta,) = vat_receipts(conn, cid, "2026-01-01", "2026-01-31").parties
    assert (beta.no_number, beta.deposit, beta.tax) == (10_000, 1_800, 1_800)
    assert (beta.advance, beta.unpaid, beta.excess, warning(beta)) == (0, 0, 0, None)
    assert vat_receipts(conn, cid, "2026-02-01", "2026-02-28").parties == []


def test_the_eqaimes_vat_paid_to_the_settlement_account(invoice_firm):
    """MS07 of 10.03, 100 + 18; on 15.03 Бета pays 118 to the bank naming it: owed
    min(18; 18 × min(118, 100)/100) = 18 — right, but the 18 beyond the value came to the
    settlement account, the deposit got nothing: min(118 − 100; 18 − 0) = 18, a warning.
    Nothing open: 118 − 118 = 0."""
    conn, ledger, cid, acc, v = invoice_firm
    sell(ledger, cid, acc, v, "Бета", "2026-03-10", "118", "18", "MS07")
    receive(ledger, cid, acc, v, "Бета", "2026-03-15", "118", "MS07")
    (beta,) = vat_receipts(conn, cid, "2026-03-01", "2026-03-31").parties
    assert (beta.by_invoice, beta.tax, beta.excess) == (11_800, 1_800, 0)
    assert (beta.advance, beta.unpaid) == (0, 0)
    assert warning(beta) == "ƏDV e-qaimə пришёл на расчётный счёт, не на депозит"


def test_the_page_shows_buyers_and_leads_to_documents(invoice_firm, qtbot):
    """January: Бета with MS01 under it; a double click on the e-qaimə opens its document,
    on the buyer — the card of the buyer."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.reports_page import ReportParams, VatReceiptsPage
    from modern_gl.desktop.reports_page.subconto_analysis import INDENT
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = invoice_firm
    receive(ledger, cid, acc, v, "Бета", "2026-01-10", "236")
    ms01 = sell(ledger, cid, acc, v, "Бета", "2026-01-20", "236", "36", "MS01")
    session = Session(conn, ledger, cid, "Firma", Catalog(conn, cid))
    page = VatReceiptsPage(session, ReportParams(date(2026, 1, 1), date(2026, 1, 31)))
    qtbot.addWidget(page)
    model = page.model
    assert page.title() == "Поступления и e-qaimə"
    assert [model.data(model.index(r, 0)) for r in range(len(model.rows))] == [
        "Бета",
        INDENT + "MS01",
        INDENT + "аванс",
        "Итого",
    ]
    assert "Предупреждений: 1" in page.footer.text()
    assert "Бета — ƏDV больше, чем в e-qaimə, на 6.48" in page.footer.text()
    opened, reports = [], []
    page.open_document.connect(opened.append)
    page.open_report.connect(lambda kind, _a, p: reports.append((kind, p.subconto)))
    page.drill(model.rows[1])
    page.drill(model.rows[0])
    assert opened == [ms01] and reports == [("subconto_card", (v["Бета"],))]
