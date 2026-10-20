"""Currency conversion (D37): what was entered, and the calculation shared by the form and
the postings. Amounts are minor units of each side's currency (None = manat)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from modern_gl.application.common import pad_subconto
from modern_gl.application.currencies import Rate, rate_on
from modern_gl.domain.currency import to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr

FEE_SIDES = ("from", "to")


@dataclass(frozen=True)
class ConversionSide:
    """One bank account of a conversion: money leaves it ("from") or comes to it ("to")."""

    account_id: int
    amount: int  # minor units of `currency_id`; 0 only in a draft
    subconto: Sequence[int | None] = ()
    currency_id: int | None = None  # None: manat
    reference: str = ""  # reference of the bank statement line


@dataclass(frozen=True)
class ConversionInput:
    doc_date: str  # the debit; the exchange difference is of this day
    source: ConversionSide | None  # a draft may lack one side
    target: ConversionSide | None
    target_date: str | None = None  # the credit, when the bank makes it later
    fee_amount: int = 0  # in the currency of the fee side
    fee_side: str = "from"
    fee_account_id: int | None = None
    memo: str = ""


@dataclass(frozen=True)
class Conversion(ConversionInput):
    id: int = 0
    document_id: int = 0
    credit_document_id: int | None = None
    number: int = 0
    status: str = "draft"


@dataclass(frozen=True)
class ConversionCalc:
    """Both sides at the Central Bank's rate of the debit date, in qəpik."""

    source_value: int | None
    target_value: int | None
    fee_value: int
    rates: dict[int, Rate] = field(default_factory=dict)
    missing: tuple[int, ...] = ()  # currencies without a rate on or before the date

    @property
    def difference(self) -> int | None:
        """Positive: a loss (less came than left), negative: a gain."""
        if self.source_value is None or self.target_value is None:
            return None
        return self.source_value - self.target_value


def calculate(conn: sqlite3.Connection, company_id: int, data: ConversionInput) -> ConversionCalc:
    rates: dict[int, Rate] = {}
    missing: list[int] = []

    def value(currency_id: int | None, amount: int) -> int | None:
        if currency_id is None:
            return amount
        if currency_id not in rates:
            rate = rate_on(conn, company_id, currency_id, data.doc_date)
            if rate is None:
                if currency_id not in missing:
                    missing.append(currency_id)
                return None
            rates[currency_id] = rate
        return to_base(amount, rates[currency_id].per_unit)

    source = data.source
    target = data.target
    source_value = value(source.currency_id, source.amount) if source else None
    target_value = value(target.currency_id, target.amount) if target else None
    fee_value = 0
    fee_side = source if data.fee_side == "from" else target
    if data.fee_amount and fee_side is not None:
        fee_value = value(fee_side.currency_id, data.fee_amount) or 0
    return ConversionCalc(source_value, target_value, fee_value, rates, tuple(missing))


def bank_rate(data: ConversionInput) -> Fraction | None:
    """The bank's rate: units of the foreign side for one unit of the other (both foreign:
    the target currency per one unit of the source, as the bank quotes a cross rate)."""
    source, target = data.source, data.target
    if source is None or target is None or not source.amount or not target.amount:
        return None
    if source.currency_id is None:  # manat -> currency: manat per unit bought
        return Fraction(source.amount, target.amount)
    return Fraction(target.amount, source.amount)


def conversion_of_document(
    conn: sqlite3.Connection, company_id: int, document_id: int
) -> int | None:
    """The conversion whose postings these are (either of its GL documents)."""
    row = conn.execute(
        "SELECT id FROM currency_conversions WHERE company_id = ? "
        "AND (document_id = ? OR credit_document_id = ?)",
        (company_id, document_id, document_id),
    ).fetchone()
    return row[0] if row else None


def find_by_reference(conn: sqlite3.Connection, company_id: int, reference: str) -> int | None:
    """A conversion already entered for a bank statement line (future statement import)."""
    reference = reference.strip()
    if not reference:
        return None
    row = conn.execute(
        "SELECT id FROM currency_conversions WHERE company_id = ? "
        "AND (from_reference = ? OR to_reference = ?) ORDER BY id LIMIT 1",
        (company_id, reference, reference),
    ).fetchone()
    return row[0] if row else None


def load_conversion(conn: sqlite3.Connection, company_id: int, conversion_id: int) -> Conversion:
    r = conn.execute(
        "SELECT c.*, d.number, d.doc_date, d.memo, d.status FROM currency_conversions c "
        "JOIN documents d ON d.company_id = c.company_id AND d.id = c.document_id "
        "WHERE c.company_id = ? AND c.id = ?",
        (company_id, conversion_id),
    ).fetchone()
    if r is None:
        raise NotFoundError(tr("документ {id} не найден", id=conversion_id))

    def side(prefix: str) -> ConversionSide | None:
        if r[f"{prefix}_account_id"] is None:
            return None
        return ConversionSide(
            r[f"{prefix}_account_id"],
            r[f"{prefix}_amount"] or 0,
            pad_subconto([r[f"{prefix}_sc{i}"] for i in (1, 2, 3)]),
            r[f"{prefix}_currency_id"],
            r[f"{prefix}_reference"],
        )

    return Conversion(
        doc_date=r["doc_date"],
        source=side("from"),
        target=side("to"),
        target_date=r["to_date"],
        fee_amount=r["fee_amount"],
        fee_side=r["fee_side"],
        fee_account_id=r["fee_account_id"],
        memo=r["memo"],
        id=r["id"],
        document_id=r["document_id"],
        credit_document_id=r["credit_document_id"],
        number=r["number"],
        status=r["status"],
    )


def same_day(data: ConversionInput) -> bool:
    return data.target_date is None or iso_date(data.target_date) == iso_date(data.doc_date)
