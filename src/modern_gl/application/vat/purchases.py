"""The purchases of the ƏDV module: the e-qaimə with what pays them. Money naming an
e-qaimə pays it; the money to a supplier without a number — an advance, or a debt paid
without saying which — pays their e-qaimə oldest first, the value apart from the ƏDV
(the user, 2026-10-29: 118 paid on 10.03 without a number, 100 of the value and 18 to the
deposit; the e-qaimə of 20.03 for 100 + 18 — the 18 credited on 20.03).

A rule of the module, not of the chart: what counts is the money to the counterparty on a
supplier's or an advance account (by its type, whatever its code — 60, 60.2, 61) and their
e-qaimə; an advance set against an e-qaimə in the books moves no money and is not read,
so the credit is the same with an advance account or without one."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from modern_gl.application.book_invoices import book_invoices
from modern_gl.application.books import COMMON
from modern_gl.application.vat.facts import InvoiceFacts, Payment, numbered_facts
from modern_gl.application.vat.sales import party_money
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection


@dataclass
class _Due:
    """What of one e-qaimə the money without a number may still pay."""

    facts: InvoiceFacts | None  # None: an e-qaimə without ƏDV — paid, nothing credited
    main: int
    vat: int


def purchase_facts(
    conn: Connection, company_id: int, date_to: date | str, layers=COMMON
) -> list[InvoiceFacts]:
    """The purchases with ƏDV up to `date_to`, by number, earliest first: the ones whose
    ƏDV went to the input VAT account."""
    found = numbered_facts(conn, company_id, date_to, layers)
    _lay_out(conn, company_id, date_to, found, layers)
    return [f for f in found.values() if f.vat > 0 and f.vat_settlement is not None and f.doc_date]


def _lay_out(
    conn: Connection,
    company_id: int,
    date_to: date | str,
    found: dict[tuple[str, str], InvoiceFacts],
    layers,
) -> None:
    """Each supplier's money without a number, oldest first, over their e-qaimə out by
    `date_to`, oldest first: the value fills what is left of the value, the ƏDV what is
    left of the ƏDV; what is left over waits for the next e-qaimə."""
    money = party_money(conn, company_id, date_to, outgoing=False, layers=layers)
    free = {m.counterparty_id: m.receipts for m in money if m.invoice is None}
    if not free:
        return
    named = {m.invoice: m.receipts for m in money if m.invoice is not None}
    dues: dict[int | None, list[_Due]] = defaultdict(list)
    for number, invoice in book_invoices(conn, company_id, outgoing=False, layers=layers).items():
        who = invoice.parties[0] if invoice.parties else None
        if who not in free or invoice.doc_date > iso_date(date_to):
            continue
        facts = found.get(("", number))
        paid = named.get(number, [])
        main = invoice.amount - sum(p.main for p in paid)
        vat = invoice.vat - sum(p.vat for p in paid)
        dues[who].append(_Due(facts, max(main, 0), max(vat, 0)))
    for who, receipts in free.items():
        for day, main, vat in _net(receipts):
            _pay(dues[who], day, main, "main")
            _pay(dues[who], day, vat, "vat")


def _net(receipts: list[Payment]) -> list[tuple[str, int, int]]:
    """The money by day with what came back taken off the latest paid before it."""
    paid: list[list] = []
    for r in receipts:
        paid.append([r.day, max(r.main, 0), max(r.vat, 0)])
        for part, back in ((1, -min(r.main, 0)), (2, -min(r.vat, 0))):
            left = back
            for row in reversed(paid):
                take = min(row[part], left)
                row[part] -= take
                left -= take
    return [(day, main, vat) for day, main, vat in paid]


def _pay(dues: list[_Due], day: str, amount: int, part: str) -> None:
    """`amount` of the value or the ƏDV, paid on `day`, to the oldest e-qaimə still due
    it (`dues` are in the order of the e-qaimə)."""
    for due in dues:
        if amount <= 0:
            return
        take = min(getattr(due, part), amount)
        if not take:
            continue
        setattr(due, part, getattr(due, part) - take)
        amount -= take
        if due.facts is not None:
            due.facts.pay(day, **{part: take})
