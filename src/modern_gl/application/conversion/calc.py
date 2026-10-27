"""Currency conversion (D37): what was entered, and the calculation shared by the form and
the postings. Amounts are minor units of each side's currency (None = manat)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from modern_gl.application.common import pad_subconto
from modern_gl.application.currencies import Rate, rate_on
from modern_gl.domain.currency import to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class ConversionSide:
    """One bank account of a conversion: money leaves it ("from") or comes to it ("to")."""

    account_id: int
    amount: int  # minor units of `currency_id`; 0 only in a draft
    subconto: Sequence[int | None] = ()
    currency_id: int | None = None  # None: manat
    reference: str = ""  # reference of the bank statement line


@dataclass(frozen=True)
class ConversionFee:
    """A bank fee: taken from any money account (either side or a third one), in its
    currency; it is an expense on `expense_account_id` (None: the account of the settings)."""

    account_id: int
    amount: int  # minor units of `currency_id`
    subconto: Sequence[int | None] = ()
    currency_id: int | None = None
    expense_account_id: int | None = None


@dataclass(frozen=True)
class ConversionInput:
    """A conversion as the form gives it: the debit and the credit side, the fees."""

    doc_date: str  # the debit; the exchange difference is of this day
    source: ConversionSide | None  # a draft may lack one side
    target: ConversionSide | None
    target_date: str | None = None  # the credit, when the bank makes it later
    fees: Sequence[ConversionFee] = ()
    memo: str = ""


@dataclass(frozen=True)
class Conversion(ConversionInput):
    """A stored conversion: its GL document (and the credit's, when made later)."""

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
    fee_values: tuple[int | None, ...] = ()  # each fee at the rate of its own day
    rates: dict[int, Rate] = field(default_factory=dict[int, Rate])  # of the debit date
    missing: tuple[int, ...] = ()  # currencies without a rate on or before the date

    @property
    def fee_total(self) -> int:
        """The fees in qəpik; one without a rate counts as nothing."""
        return sum(v or 0 for v in self.fee_values)

    @property
    def difference(self) -> int | None:
        """Positive: a loss (less came than left), negative: a gain."""
        if self.source_value is None or self.target_value is None:
            return None
        return self.source_value - self.target_value


def fee_on_credit(data: ConversionInput, fee: ConversionFee) -> bool:
    """A fee taken from the account credited goes with the credit (on its day, when the bank
    credits later); any other fee goes with the debit."""
    target = data.target
    return (
        target is not None
        and fee.account_id == target.account_id
        and pad_subconto(fee.subconto) == pad_subconto(target.subconto)
    )


def fee_date(data: ConversionInput, fee: ConversionFee) -> str:
    """The day of a fee: the credit's when it goes with a later credit, else the debit's."""
    if fee_on_credit(data, fee) and data.target_date:
        return data.target_date
    return data.doc_date


def calculate(conn: Connection, company_id: int, data: ConversionInput) -> ConversionCalc:
    """Both sides at the rate of the debit date, each fee at the rate of its day; the
    currencies without a rate are named, their values None."""
    rates: dict[tuple[int, str], Rate] = {}
    missing: list[int] = []

    def value(currency_id: int | None, amount: int, day: str) -> int | None:
        if currency_id is None:
            return amount
        if (currency_id, day) not in rates:
            rate = rate_on(conn, company_id, currency_id, day)
            if rate is None:
                if currency_id not in missing:
                    missing.append(currency_id)
                return None
            rates[currency_id, day] = rate
        return to_base(amount, rates[currency_id, day].per_unit)

    source, target, day = data.source, data.target, data.doc_date
    source_value = value(source.currency_id, source.amount, day) if source else None
    target_value = value(target.currency_id, target.amount, day) if target else None
    fees = tuple(value(f.currency_id, f.amount, fee_date(data, f)) for f in data.fees)
    of_day = {c: r for (c, d), r in rates.items() if d == day}
    return ConversionCalc(source_value, target_value, fees, of_day, tuple(missing))


def bank_rate(data: ConversionInput) -> Fraction | None:
    """The bank's rate: units of the foreign side for one unit of the other (both foreign:
    the target currency per one unit of the source, as the bank quotes a cross rate)."""
    source, target = data.source, data.target
    if source is None or target is None or not source.amount or not target.amount:
        return None
    if source.currency_id is None:  # manat -> currency: manat per unit bought
        return Fraction(source.amount, target.amount)
    return Fraction(target.amount, source.amount)


def official_rate(data: ConversionInput, rates: Mapping[int, Rate]) -> Fraction | None:
    """The Central Bank's rate quoted as the bank quotes (see bank_rate): manat per unit
    bought or sold; for a cross — the target per one unit of the source, from the two
    official rates. None: a side is not chosen or a rate is missing."""
    if data.source is None or data.target is None:
        return None
    src, tgt = data.source.currency_id, data.target.currency_id
    per_unit = {c: r.per_unit for c, r in rates.items()}
    if src is None:
        return per_unit.get(tgt) if tgt is not None else None
    if src not in per_unit:
        return None
    if tgt is None:
        return per_unit[src]
    return per_unit[src] / per_unit[tgt] if tgt in per_unit else None


def load_conversion(conn: Connection, company_id: int, conversion_id: int) -> Conversion:
    """A conversion with its document's number, date, memo and status, and its fees."""
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
        fees=tuple(
            ConversionFee(
                f["account_id"],
                f["amount"],
                (f["sc1"], f["sc2"], f["sc3"]),
                f["currency_id"],
                f["expense_account_id"],
            )
            for f in conn.execute(
                "SELECT * FROM conversion_fees WHERE company_id = ? AND conversion_id = ? "
                "ORDER BY line_no",
                (company_id, conversion_id),
            )
        ),
        memo=r["memo"],
        id=r["id"],
        document_id=r["document_id"],
        credit_document_id=r["credit_document_id"],
        number=r["number"],
        status=r["status"],
    )


def same_day(data: ConversionInput) -> bool:
    """Whether the bank credits on the day of the debit (one GL document)."""
    return data.target_date is None or iso_date(data.target_date) == iso_date(data.doc_date)
