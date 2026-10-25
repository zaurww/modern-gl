"""When and how much of a purchase's ƏDV is credited: the events of one number under a
version of the rule. Pure arithmetic in kopecks."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.vat.facts import InvoiceFacts
from modern_gl.application.vat.rules import CreditRule
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import round_ratio


@dataclass(frozen=True)
class CreditEvent:
    day: str
    amount: int


def allowed(facts: InvoiceFacts, rule: CreditRule, paid_main: int, paid_vat: int) -> int:
    """The ƏDV creditable once `paid_main` of the amount and `paid_vat` of the ƏDV are
    paid: a declaration — the ƏDV paid; an e-qaimə — the ƏDV paid, but no more than the
    share of the amount paid (or nothing until paid in full)."""
    vat_paid = max(min(paid_vat, facts.vat), 0)
    if facts.kind == CUSTOMS:
        return vat_paid
    if not rule.partial_share:
        return facts.vat if paid_main >= facts.amount and paid_vat >= facts.vat else 0
    if facts.amount <= 0:
        return vat_paid
    share = round_ratio(facts.vat * max(min(paid_main, facts.amount), 0), facts.amount)
    return min(vat_paid, share)


def credit_events(facts: InvoiceFacts, rule: CreditRule) -> list[CreditEvent]:
    """The days the credit grows and by how much: each payment, in order, on its day —
    not before the document's day (an advance waits for the e-qaimə). Together they are
    the ƏDV creditable so far; the rest waits."""
    events: list[CreditEvent] = []
    paid_main = paid_vat = credited = 0
    for payment in sorted(facts.payments, key=lambda p: p.day):
        paid_main += payment.main
        paid_vat += payment.vat
        now = allowed(facts, rule, paid_main, paid_vat)
        if now == credited:
            continue
        day = max(payment.day, facts.doc_date)
        if events and events[-1].day == day:
            events[-1] = CreditEvent(day, events[-1].amount + now - credited)
        else:
            events.append(CreditEvent(day, now - credited))
        credited = now
    return [e for e in events if e.amount]
