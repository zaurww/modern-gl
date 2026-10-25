"""«ƏDV продаж к уплате»: the ƏDV a period's sales owe — on the day money came from the
buyer (an advance too) or the e-qaimə changed the share — by e-qaimə or advance
(`application/vat`, Tax Code 166). A day money came but nothing more is owed shows too,
with 0: the ƏDV was owed already."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.vat import liability_events, liability_rule_for, sale_facts
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class LiabilityRow:
    day: str
    invoice: str | None  # None: an advance without an e-qaimə
    counterparty: str
    main: int  # received on the day to a bank account or the cash desk (the value)
    vat: int  # received on the day to the ƏDV deposit account
    owed: int  # the ƏDV owed by the day's change


@dataclass
class VatLiability:
    rows: list[LiabilityRow] = field(default_factory=list)
    owed: int = 0  # in the period


def vat_liability(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatLiability:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    liability_rule_for(date_from)  # a period before the known rules is refused
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
        )
    }
    result = VatLiability()
    for facts in sale_facts(conn, company_id, date_to):
        name = names.get(facts.counterparty_id or 0, "")
        for e in liability_events(facts):
            if date_from <= e.day <= date_to:
                result.rows.append(
                    LiabilityRow(e.day, facts.invoice, name, e.main, e.vat, e.amount)
                )
                result.owed += e.amount
    result.rows.sort(key=lambda r: (r.day, r.counterparty, r.invoice or ""))
    return result
