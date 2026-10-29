"""Stage 4 of the ƏDV declaration (D145): ƏDV paid to the supplier's deposit straight
from a bank account (`pays_vat`), in part from the deposit; an advance paid to the
supplier's deposit without a number, set against the e-qaimə later; and the day the
company became a payer of ƏDV. Every figure is worked out by hand in the docstring."""

from __future__ import annotations

from modern_gl.application.bank import (
    OUT,
    SUPPLIER,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.ledger import PostingInput
from modern_gl.reporting.vat import vat_credit
from modern_gl.reporting.vat_liability import vat_liability
from modern_gl.reporting.vat_payments import vat_payments
from tests.helpers.vat_credit import buy, events, pay, post
from tests.helpers.vat_liability import receive


def bank_payment(ledger, cid, acc, v, day: str, *lines: tuple[int, str, bool]) -> int:
    """A payment to Альфа from the bank account: lines of (kopecks, e-qaimə, ƏDV)."""
    data = BankOperationInput(
        doc_date=day,
        direction=OUT,
        account_id=acc["51"],
        subconto=(v["Kapital"],),
        kind=SUPPLIER,
        counterparty_id=v["Альфа"],
        lines=tuple(
            BankLine(acc["60"], amount, (v["Альфа"], v["Д-1"]), number, pays_vat=vat)
            for amount, number, vat in lines
        ),
    )
    return ledger.bank.save_bank_operation(cid, data, post=True)


def test_the_vat_paid_from_the_bank_account_is_credited(invoice_firm):
    """MT01 of 05.03, 1 000 + 180. On 10.03 one bank payment: 1 000 for the value and 180
    straight to Альфа's deposit — credited 180 on 10.03. The same as an ordinary payment
    (MT02, 1 180 from the bank, no mark) credits nothing: the ƏDV did not reach the
    deposit."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT01")
    op = bank_payment(
        ledger, cid, acc, v, "2026-03-10", (100_000, "MT01", False), (18_000, "MT01", True)
    )
    assert [line.pays_vat for line in load_bank_operation(conn, cid, op).lines] == [False, True]
    assert events(conn, cid, "MT01") == [("2026-03-10", 18_000)]
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT02")
    bank_payment(ledger, cid, acc, v, "2026-03-10", (118_000, "MT02", False))
    assert events(conn, cid, "MT02") == []


def test_the_vat_in_part_from_the_bank_in_part_from_the_deposit(invoice_firm):
    """MT03 of 05.03, 1 000 + 180: on 10.03 1 000 and 100 of the ƏDV from the bank, the
    other 80 from the deposit — the ƏDV paid is 100 + 80 = 180, all credited on 10.03.
    «Оплаты поставщикам» shows 180 «с депозита ƏDV», no warning."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-03-05", "1000", "180", "MT03")
    bank_payment(
        ledger, cid, acc, v, "2026-03-10", (100_000, "MT03", False), (10_000, "MT03", True)
    )
    pay(ledger, cid, acc, v, "2026-03-10", "80", "MT03", deposit=True)
    assert events(conn, cid, "MT03") == [("2026-03-10", 18_000)]
    (alfa,) = vat_payments(conn, cid, "2026-03-01", "2026-03-31").parties
    assert (alfa.by_invoice, alfa.deposit, alfa.tax, alfa.excess) == (100_000, 18_000, 18_000, 0)


def test_an_advance_to_the_deposit_set_against_the_eqaime(invoice_firm):
    """On 01.03 Альфа gets an advance without a number: 500 from the bank (Dt 61 / Kt 51)
    and 90 from our deposit (Dt 61 / Kt 54) — an ƏDV advance of 90. MT04 of 15.03,
    500 + 90: the advance pays it — 90 of the ƏDV, 500 of the value — credited 90 on 15.03,
    the e-qaimə's day (the money was there before); setting the advance against it on 20.03
    (Dt 60 / Kt 61 590, MT04) moves no money and changes nothing; no warning. Without the
    deposit part (MT05: 590 from the bank to 61 on 02.03, set against on 21.03) — 590 of
    the value, nothing credited."""
    conn, ledger, cid, acc, v = invoice_firm
    alfa = (v["Альфа"], v["Д-1"])
    post(
        ledger, cid, "2026-03-01", PostingInput(acc["61"], acc["51"], "500", alfa, (v["Kapital"],))
    )
    post(ledger, cid, "2026-03-01", PostingInput(acc["61"], acc["54"], "90", alfa, (v["Kapital"],)))
    buy(ledger, cid, acc, v, "2026-03-15", "500", "90", "MT04")
    post(
        ledger,
        cid,
        "2026-03-20",
        PostingInput(acc["60"], acc["61"], "590", alfa, alfa, invoice="MT04"),
    )
    assert events(conn, cid, "MT04") == [("2026-03-15", 9_000)]
    (row,) = vat_payments(conn, cid, "2026-03-01", "2026-03-31").parties
    assert (row.no_number, row.deposit, row.tax, row.excess, row.reason) == (
        50_000,
        9_000,
        9_000,
        0,
        "",
    )

    post(
        ledger, cid, "2026-04-02", PostingInput(acc["61"], acc["51"], "590", alfa, (v["Kapital"],))
    )
    buy(ledger, cid, acc, v, "2026-04-15", "500", "90", "MT05")
    post(
        ledger,
        cid,
        "2026-04-21",
        PostingInput(acc["60"], acc["61"], "590", alfa, alfa, invoice="MT05"),
    )
    assert events(conn, cid, "MT05") == []


def test_before_the_company_pays_vat_nothing_is_owed_or_credited(invoice_firm):
    """The company pays ƏDV from 15.03. Sales: an advance of 100 from Бета on 10.03 —
    before the day, nothing owed (it would be 18); 50 on 20.03 — 9 owed. March owes 9.
    Purchases: MT06 of 10.03 (1 000 + 180, paid in full on 12.03) — bought before, not
    credited and no warning; MT07 of 16.03, the same, paid on 20.03 — 180 credited.
    Set back to «all along», March owes 18 + 9 = 27 and credits 180 + 180 = 360."""
    conn, ledger, cid, acc, v = invoice_firm
    ledger.set_vat_payer_from(cid, "2026-03-15")
    receive(ledger, cid, acc, v, "2026-03-10", "100", None)
    receive(ledger, cid, acc, v, "2026-03-20", "50", None)
    for number, day, paid in (
        ("MT06", "2026-03-10", "2026-03-12"),
        ("MT07", "2026-03-16", "2026-03-20"),
    ):
        buy(ledger, cid, acc, v, day, "1000", "180", number)
        pay(ledger, cid, acc, v, paid, "1000", number)
        pay(ledger, cid, acc, v, paid, "180", number, deposit=True)

    march = vat_liability(conn, cid, "2026-03-01", "2026-03-31")
    assert (march.owed, march.payer_from) == (900, "2026-03-15")
    credit = vat_credit(conn, cid, "2026-03-01", "2026-03-31")
    assert [(r.invoice, r.credited) for r in credit.rows] == [("MT07", 18_000)]
    assert (credit.credited, credit.waiting) == (18_000, 0)
    (alfa,) = vat_payments(conn, cid, "2026-03-01", "2026-03-31").parties
    assert (alfa.tax, alfa.excess, alfa.reason) == (18_000, 0, "")

    ledger.set_vat_payer_from(cid, None)
    assert vat_liability(conn, cid, "2026-03-01", "2026-03-31").owed == 2_700
    assert vat_credit(conn, cid, "2026-03-01", "2026-03-31").credited == 36_000


def test_the_mark_goes_out_and_comes_back_in_the_exchange_file(invoice_firm):
    """A payment of 180 from the bank to Альфа's deposit (MT09) goes out with
    "pays_vat": true, and a line with it comes back marked; anything but true or false
    is refused."""
    import pytest

    from modern_gl.application.catalog import Catalog
    from modern_gl.application.exchange.lines import posting_lines
    from modern_gl.reporting.exchange import documents_file

    conn, ledger, cid, acc, v = invoice_firm
    bank_payment(ledger, cid, acc, v, "2026-03-10", (18_000, "MT09", True))
    (doc,) = documents_file(conn, cid, "2026-03-01", "2026-03-31")["documents"]
    (line,) = doc["postings"]
    assert (line["e_qaime"], line["amount"], line["pays_vat"]) == ("MT09", "180.00", True)
    (back,) = posting_lines(Catalog(conn, cid), doc["postings"], exact=True)
    assert back.pays_vat and back.invoice == "MT09"
    with pytest.raises(ValueError, match="pays_vat"):
        posting_lines(Catalog(conn, cid), [{**line, "pays_vat": "yes"}], exact=True)
