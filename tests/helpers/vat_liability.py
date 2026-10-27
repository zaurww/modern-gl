"""Shared from test_vat_liability.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from tests.helpers.vat_credit import post


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
