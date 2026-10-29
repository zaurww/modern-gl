"""«Оплаты поставщикам и e-qaimə»: the money paid to each supplier set against the e-qaimə
they issued — the purchases' side of the check by counterparty (`reporting/vat_receipts`).
For the period: paid from a bank account or the cash desk (naming an e-qaimə or not) and
from the ƏDV deposit, the e-qaimə received, the ƏDV credited (D138). At the period's end:
an advance no e-qaimə closes, e-qaimə not paid, and the ƏDV of e-qaimə paid but not
credited — mostly ƏDV not paid to the supplier's deposit (D138); money without a number
pays the e-qaimə oldest first in the credit too (`application/vat/purchases`, D185)."""

from __future__ import annotations

from datetime import date

from modern_gl.application.book_invoices import BookInvoice, book_invoices
from modern_gl.application.vat import (
    credit_events,
    party_money,
    payer_from,
    purchase_facts,
    rule_for,
)
from modern_gl.domain.money import round_ratio
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.vat_receipts import (
    NO_NUMBER,
    NOT_TO_DEPOSIT,
    Parties,
    PartyRow,
    ReceiptLine,
    VatReceipts,
    collect,
    issue,
    keep,
    money_line,
    period,
)


def vat_payments(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatReceipts:
    date_from, date_to = period(date_from, date_to)
    rule = rule_for(date_from)  # as «ƏDV к зачёту»; a period before the rules is refused
    bought = book_invoices(conn, company_id, outgoing=False)
    # number: (credited in the period, by its end; the value paid naming it)
    credits: dict[str, tuple[int, int, int]] = {}
    since = payer_from(conn, company_id)  # bought before it — no credit, nothing to warn
    for facts in purchase_facts(conn, company_id, date_to):
        if not facts.kind and facts.doc_date >= since:
            events = credit_events(facts, rule)
            credits[facts.invoice] = (
                sum(e.amount for e in events if e.day >= date_from),
                sum(e.amount for e in events),
                sum(p.main for p in facts.payments),
            )
    parties = Parties(conn, company_id)
    numbers = set()
    for facts in party_money(conn, company_id, date_to, outgoing=False):
        numbers.add(facts.invoice)
        row = parties.of(facts.counterparty_id)
        invoice = bought.get(facts.invoice) if facts.invoice is not None else None
        line, paid = money_line(facts, date_from)
        if not _issue(row, line, invoice, paid, credits, date_from, date_to):
            row.free_money += paid
        keep(row, line)
    for number, invoice in bought.items():
        if number not in numbers:
            line = ReceiptLine(number)
            row = parties.of(invoice.parties[0] if invoice.parties else None)
            _issue(row, line, invoice, 0, credits, date_from, date_to)
            keep(row, line)
    return collect(parties, lambda row: _close(row, since), since)


def _issue(
    row: PartyRow,
    line: ReceiptLine,
    invoice: BookInvoice | None,
    paid: int,
    credits: dict[str, tuple[int, int, int]],
    date_from: str,
    date_to: str,
) -> bool:
    """The e-qaimə of the line with its credit."""
    now, by_end, named = credits.get(line.invoice or "", (0, 0, 0))
    if not issue(row, line, invoice, paid, date_from, date_to, by_end, named):
        return False
    line.tax = now
    return True


def _close(row: PartyRow, since: str) -> None:
    """The ƏDV of what is paid of each e-qaimə, beyond what is credited — a warning: its
    value paid without the number, or its ƏDV not to the deposit."""
    for i in row.issued:
        if not i.total or i.day < since:
            continue
        covered = min(max(i.got, 0), i.total) + i.extra
        short = max(round_ratio(i.vat * covered, i.total) - i.credited, 0)
        if short:
            row.excess += short
            if i.named < round_ratio((i.total - i.vat) * covered, i.total):
                row.reason = NO_NUMBER
            elif row.reason != NO_NUMBER:
                row.reason = NOT_TO_DEPOSIT
