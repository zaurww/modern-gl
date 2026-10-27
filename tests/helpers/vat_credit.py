"""Shared from test_vat_credit.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.application.ledger import PostingInput
from modern_gl.application.vat import (
    CreditRule,
    credit_events,
    purchase_facts,
)

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
