"""«Реестр e-qaimə» for the ƏDV declaration (docs/REPORTING.md, «Этапы до декларации
ƏDV», stage 1): the purchases and the sales of a period, apart, by the day of the
e-qaimə (customs declaration) — number, counterparty, VÖEN, amount without ƏDV, ƏDV,
total, what is unpaid at the period's end; the totals by rate.

An e-qaimə is its accrual and its ƏDV, as the reconciliation with the portal counts it
(`book_invoices`, D120); its day is the first accrual's. Customs declarations are
purchases only. A correction belongs to the period of its e-qaimə, whenever it is posted
(D140): the register of a month is what that month's declaration says now — an amended
one, if the month changed after it was filed; the difference reaches the account with
the budget on the day the amended declaration is filed. Unpaid — the settlement accounts'
balance of the number at the period's end (`gathered_invoices`), a purchase paid to the
supplier, a declaration to the customs too.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.book_invoices import BookInvoice, book_invoices
from modern_gl.application.books import COMMON, book_params
from modern_gl.application.invoices import IN_PERIOD, gathered_invoices
from modern_gl.domain.dates import iso_date, next_day
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import CUSTOMS, EQAIME
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.eqaime_reconciliation import (
    Mark,
    books_changed,
    changed_after_reconciliation,
    reconciled_periods,
)


@dataclass(frozen=True)
class RegisterRow:
    kind: str  # domain.invoice: EQAIME, CUSTOMS a declaration
    invoice: str
    doc_date: str
    counterparty: str
    tax_id: str
    amount: int  # without ƏDV
    vat: int
    unpaid: int  # at the period's end; < 0 — paid more
    document_id: int | None  # the first accrual's

    @property
    def total(self) -> int:
        return self.amount + self.vat

    @property
    def rate(self) -> int | None:
        """The ƏDV rate in whole percent (18), None — without ƏDV."""
        if not self.vat:
            return None
        return round_ratio(self.vat * 100, self.amount) if self.amount else 100


@dataclass(frozen=True)
class RateTotal:
    rate: int | None  # None: without ƏDV
    count: int
    amount: int
    vat: int

    @property
    def total(self) -> int:
        return self.amount + self.vat


# how the period stands with the portal, per direction (stage 2): the worst first
BOOKS_CHANGED = "books"  # marked reconciled, then an e-qaimə changed in the books (D140)
PORTAL_CHANGED = "portal"  # marked reconciled, then an e-qaimə changed on the portal
NOT_RECONCILED = "not"  # some day of the period is not marked reconciled
RECONCILED = "reconciled"


@dataclass(frozen=True)
class PortalCheck:
    outgoing: bool
    state: str
    numbers: tuple[str, ...] = ()  # PORTAL_CHANGED: the e-qaimə that changed

    @property
    def agrees(self) -> bool:
        return self.state == RECONCILED


@dataclass
class VatRegister:
    purchases: list[RegisterRow] = field(default_factory=list)
    sales: list[RegisterRow] = field(default_factory=list)
    checks: list[PortalCheck] = field(default_factory=list)  # purchases, then sales

    @property
    def purchase_rates(self) -> list[RateTotal]:
        return rate_totals(self.purchases)

    @property
    def sale_rates(self) -> list[RateTotal]:
        return rate_totals(self.sales)


def vat_register(
    conn: Connection, company_id: int, date_from: date | str, date_to: date | str
) -> VatRegister:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    params = book_params(conn, company_id, date_from, date_to, COMMON)
    # an e-qaimə dated in the period has a posting in it: only those numbers are read
    balances = {
        key: r.balance
        for key, r in gathered_invoices(conn, company_id, params, only=IN_PERIOD).items()
    }
    names = _directory(conn, company_id)

    def rows(outgoing: bool, kind: str) -> list[RegisterRow]:
        found = book_invoices(conn, company_id, outgoing, kind=kind, period=(date_from, date_to))
        sign = 1 if outgoing else -1  # a sale owes Dt, a purchase Kt
        return [
            _row(kind, b, names, sign * balances.get((kind, b.number), 0))
            for b in found.values()
            if date_from <= b.doc_date <= date_to
        ]

    def order(found: list[RegisterRow]) -> list[RegisterRow]:
        return sorted(found, key=lambda r: (r.doc_date, r.kind, r.invoice))

    return VatRegister(
        purchases=order(rows(False, EQAIME) + rows(False, CUSTOMS)),
        sales=order(rows(True, EQAIME)),
        checks=[portal_check(conn, company_id, out, date_from, date_to) for out in (False, True)],
    )


def portal_check(
    conn: Connection, company_id: int, outgoing: bool, date_from: str, date_to: str
) -> PortalCheck:
    """Whether the e-qaimə of the period agree with the portal: every day of it marked
    reconciled (D118), and neither the books nor the portal changed since. Customs
    declarations are not on the portal and need no check."""

    def touches(start: str, end: str) -> bool:
        return start <= date_to and end >= date_from

    if any(touches(m.date_from, m.date_to) for m in books_changed(conn, company_id, outgoing)):
        return PortalCheck(outgoing, BOOKS_CHANGED)
    months = [
        c
        for c in changed_after_reconciliation(conn, company_id)
        if c.outgoing == outgoing and date_from[:7] <= c.month <= date_to[:7]
    ]
    if months:
        numbers = tuple(dict.fromkeys(n for c in months for n in c.numbers))
        return PortalCheck(outgoing, PORTAL_CHANGED, numbers)
    marks = reconciled_periods(conn, company_id, outgoing)
    if not _covered(marks, date_from, date_to):
        return PortalCheck(outgoing, NOT_RECONCILED)
    return PortalCheck(outgoing, RECONCILED)


def _covered(marks: Iterable[Mark], date_from: str, date_to: str) -> bool:
    """Every day from `date_from` to `date_to` lies in some marked period."""
    day = date_from
    for mark in sorted(marks, key=lambda m: m.date_from):
        if mark.date_from > day:
            break
        if mark.date_to >= day:
            day = next_day(mark.date_to)
        if day > date_to:
            return True
    return False


def rate_totals(rows: Iterable[RegisterRow]) -> list[RateTotal]:
    """The rows summed by rate, the highest first, without ƏDV last."""
    sums: dict[int | None, list[int]] = {}
    for r in rows:
        count, amount, vat = sums.setdefault(r.rate, [0, 0, 0])
        sums[r.rate] = [count + 1, amount + r.amount, vat + r.vat]
    ordered = sorted(sums, key=lambda rate: -1 if rate is None else rate, reverse=True)
    return [RateTotal(rate, *sums[rate]) for rate in ordered]


def _row(kind: str, b: BookInvoice, names: dict[int, tuple[str, str]], unpaid: int):
    name, tax_id = names.get(b.parties[0], ("", "")) if b.parties else ("", "")
    document = b.documents[0][0] if b.documents else None
    return RegisterRow(kind, b.number, b.doc_date, name, tax_id, b.amount, b.vat, unpaid, document)


def _directory(conn: Connection, company_id: int) -> dict[int, tuple[str, str]]:
    return {
        r["id"]: (r["name"], r["tax_id"] or "")
        for r in conn.execute(
            "SELECT id, name, tax_id FROM subconto_values WHERE company_id = ?", (company_id,)
        )
    }
