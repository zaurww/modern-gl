"""Money to a supplier without a number pays their e-qaimə oldest first — a rule of the ƏDV
module, the same whatever account the books keep the advance on (60 or 61). Every figure
is worked out by hand in the docstring."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from tests.helpers.vat_credit import buy, events, post


def free(ledger, cid, acc, v, day: str, amount: str, source: str = "51", to: str = "60") -> None:
    """Dt 60 (61) / Kt 51 (54 — the ƏDV deposit) to Альфа, no number; Dt 51 / Kt 60 — back."""
    alfa = (v["Альфа"], v["Д-1"])
    line = (
        PostingInput(acc[source], acc[to], amount[1:], (v["Kapital"],), alfa)
        if amount.startswith("-")
        else PostingInput(acc[to], acc[source], amount, alfa, (v["Kapital"],))
    )
    post(ledger, cid, day, line)


def test_the_users_example_on_one_settlement_account(invoice_firm):
    """10.03: 100 from the bank and 18 from the deposit to Альфа on 60, no number — an
    advance, nothing to credit. 20.03: MT01 100 + 18 — the advance pays it, the 18 is
    credited on 20.03. The same money on 61 (an advance account) credits the same."""
    conn, ledger, cid, acc, v = invoice_firm
    free(ledger, cid, acc, v, "2026-03-10", "100")
    free(ledger, cid, acc, v, "2026-03-10", "18", source="54")
    buy(ledger, cid, acc, v, "2026-03-20", "100", "18", "MT01")
    assert events(conn, cid, "MT01") == [("2026-03-20", 1_800)]


def test_an_advance_on_61_credits_the_same(invoice_firm):
    conn, ledger, cid, acc, v = invoice_firm
    free(ledger, cid, acc, v, "2026-03-10", "100", to="61")
    free(ledger, cid, acc, v, "2026-03-10", "18", source="54", to="61")
    buy(ledger, cid, acc, v, "2026-03-20", "100", "18", "MT01")
    assert events(conn, cid, "MT01") == [("2026-03-20", 1_800)]


def test_money_without_a_number_pays_the_oldest_eqaime_first(invoice_firm):
    """MA1 of 01.04, 200 + 36; MA2 of 05.04, 300 + 54. 10.04, no number: 400 from the bank
    and 72 from the deposit. The value: MA1 200, MA2 the other 200; the ƏDV: MA1 36, MA2
    36. MA1 is paid in full — 36 on 10.04; MA2 — 54 × 200 / 300 = 36 of the share, 36 of
    the ƏDV paid — 36 on 10.04, 18 waits."""
    conn, ledger, cid, acc, v = invoice_firm
    buy(ledger, cid, acc, v, "2026-04-01", "200", "36", "MA1")
    buy(ledger, cid, acc, v, "2026-04-05", "300", "54", "MA2")
    free(ledger, cid, acc, v, "2026-04-10", "400")
    free(ledger, cid, acc, v, "2026-04-10", "72", source="54")
    assert events(conn, cid, "MA1") == [("2026-04-10", 3_600)]
    assert events(conn, cid, "MA2") == [("2026-04-10", 3_600)]


def test_an_older_eqaime_without_vat_takes_its_share(invoice_firm):
    """NV1 of 01.05, 100 without ƏDV (Dt 26 / Kt 60); MV2 of 05.05, 100 + 18. 10.05, no
    number: 150 from the bank, 18 from the deposit. The value: NV1 100, MV2 50; the ƏDV:
    MV2 18. MV2: 18 × 50 / 100 = 9 of the share — 9 on 10.05."""
    conn, ledger, cid, acc, v = invoice_firm
    alfa = (v["Альфа"], v["Д-1"])
    post(
        ledger,
        cid,
        "2026-05-01",
        PostingInput(acc["26"], acc["60"], "100", (v["Аренда"],), alfa, invoice="NV1"),
    )
    buy(ledger, cid, acc, v, "2026-05-05", "100", "18", "MV2")
    free(ledger, cid, acc, v, "2026-05-10", "150")
    free(ledger, cid, acc, v, "2026-05-10", "18", source="54")
    assert events(conn, cid, "MV2") == [("2026-05-10", 900)]


def test_money_back_is_no_payment(invoice_firm):
    """01.06: 100 from the bank and 18 from the deposit to Альфа, no number; 03.06 Альфа
    sends the 100 back. MR of 10.06, 100 + 18: the value is not paid — 18 × 0 / 100 = 0,
    nothing credited."""
    conn, ledger, cid, acc, v = invoice_firm
    free(ledger, cid, acc, v, "2026-06-01", "100")
    free(ledger, cid, acc, v, "2026-06-01", "18", source="54")
    free(ledger, cid, acc, v, "2026-06-03", "-100")
    buy(ledger, cid, acc, v, "2026-06-10", "100", "18", "MR")
    assert events(conn, cid, "MR") == []
