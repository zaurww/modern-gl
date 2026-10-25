"""When and how much ƏDV a sale owes (`LiabilityRule`): what is owed up to a day is the
larger of the ƏDV received and the ƏDV of the value received; each day that changes it is
an event of the difference. Pure arithmetic in kopecks."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.vat.rules import LiabilityRule, liability_rule_for
from modern_gl.application.vat.sales import SaleFacts
from modern_gl.domain.money import round_ratio


@dataclass(frozen=True)
class LiabilityEvent:
    day: str
    amount: int  # < 0: less is owed now (money returned, an e-qaimə without ƏDV)
    main: int  # the value received on the day
    vat: int  # the ƏDV received on the day


def owed(facts: SaleFacts, day: str, main: int, vat: int, rule: LiabilityRule) -> int:
    """What is owed on `day` once `main` of the value and `vat` of the ƏDV are received:
    with the e-qaimə out by then — its ƏDV in the share of its value received, no more
    than its ƏDV; before it (an advance) — `rule.rate` percent of the value."""
    if facts.doc_date and facts.doc_date <= day:
        if facts.amount <= 0:
            return max(min(vat, facts.vat), 0)
        share = round_ratio(facts.vat * max(min(main, facts.amount), 0), facts.amount)
        return max(min(max(vat, share), facts.vat), 0)
    return max(vat, round_ratio(main * rule.rate, 100), 0)


def liability_events(facts: SaleFacts) -> list[LiabilityEvent]:
    """The days what is owed changes — on a receipt, and on the e-qaimə's day (the share
    of an advance becomes the e-qaimə's) — by how much, under the rule of each day."""
    days = sorted({r.day for r in facts.receipts} | ({facts.doc_date} - {""}))
    by_day = {r.day: r for r in facts.receipts}
    events: list[LiabilityEvent] = []
    main = vat = before = 0
    for day in days:
        receipt = by_day.get(day)
        got_main, got_vat = (receipt.main, receipt.vat) if receipt else (0, 0)
        main, vat = main + got_main, vat + got_vat
        now = owed(facts, day, main, vat, liability_rule_for(day))
        if now != before or receipt is not None:
            events.append(LiabilityEvent(day, now - before, got_main, got_vat))
        before = now
    return events
