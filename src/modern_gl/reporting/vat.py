"""«ƏDV к зачёту»: the input ƏDV credited in a period, by the e-qaimə or customs
declaration and the day the credit came (`application/vat`), and what still waits for an
e-qaimə or a payment at the period's end. The rule is the version in force at the period's
start (docs/REPORTING.md, «Модуль ƏDV»)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.vat import credit_events, payer_from, purchase_facts, rule_for
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class CreditRow:
    day: str  # the credit's day
    kind: str  # domain.invoice: "" an e-qaimə, "customs" a declaration
    invoice: str
    counterparty: str
    document_id: int | None  # the GL document of the e-qaimə (declaration)
    vat: int  # the document's ƏDV
    credited: int  # on this day
    before: int  # credited before the period
    waiting: int  # of the document's ƏDV, not yet creditable at the period's end


@dataclass
class VatCredit:
    rows: list[CreditRow] = field(default_factory=list)
    credited: int = 0  # in the period
    waiting: int = 0  # at the period's end, over every purchase
    waiting_count: int = 0  # purchases with something waiting
    payer_from: str = ""  # the company pays ƏDV since (D145); "" — all along


def vat_credit(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatCredit:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    rule = rule_for(date_from)
    names = _names(conn, company_id)
    result = VatCredit(payer_from=payer_from(conn, company_id))
    for facts in purchase_facts(conn, company_id, date_to):
        if facts.doc_date < result.payer_from:  # bought before the company paid ƏDV
            continue
        events = credit_events(facts, rule)
        before = sum(e.amount for e in events if e.day < date_from)
        total = sum(e.amount for e in events)
        waiting = facts.vat - total
        name = names.get(facts.counterparty_id or 0, "")
        for e in events:
            if date_from <= e.day <= date_to:
                result.rows.append(
                    CreditRow(
                        e.day,
                        facts.kind,
                        facts.invoice,
                        name,
                        facts.document_id,
                        facts.vat,
                        e.amount,
                        before,
                        waiting,
                    )
                )
                before += e.amount
                result.credited += e.amount
        if waiting > 0:
            result.waiting += waiting
            result.waiting_count += 1
    result.rows.sort(key=lambda r: (r.day, r.kind, r.invoice))
    return result


def _names(conn: Connection, company_id: int) -> dict[int, str]:
    return {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
        )
    }
