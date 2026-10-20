"""Inputs of the ledger use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

DEFAULT_LAYERS = (
    ("common", "Общий учёт"),
    ("ifrs_adj", "Корректировки МСФО"),
    ("tax_adj", "Налоговые корректировки"),
)

SIDES = (("debit", "dt"), ("credit", "ct"))


@dataclass(frozen=True)
class PostingInput:
    """One Dt/Ct pair. Subconto values are given per position (1..3) of each account."""

    debit_account_id: int
    credit_account_id: int
    amount: str | int | Decimal
    debit_subconto: Sequence[int | None] = ()
    credit_subconto: Sequence[int | None] = ()
    memo: str = ""
    # Currency accounts (52, settlements in USD…): the currency and the amount in it.
    # One currency per posting, for whichever of its sides keeps currency.
    currency_id: int | None = None
    currency_amount: str | int | Decimal | None = None
    invoice: str = ""  # number of the e-qaimə the posting belongs to ("" = none)


@dataclass(frozen=True)
class TemplateLine:
    """A line of an entry template. Anything left empty is filled in by hand."""

    debit_account_id: int | None = None
    credit_account_id: int | None = None
    formula: str = ""  # amount: S, S*18/118, S-L2… (see domain.formula); "" = by hand
    debit_subconto: Sequence[int | None] = ()
    credit_subconto: Sequence[int | None] = ()
    memo: str = ""


@dataclass(frozen=True)
class ImportedDocument:
    doc_date: date | str
    postings: Sequence[PostingInput]
    memo: str = ""
    layer: str = "common"


@dataclass
class ImportOutcome:
    ids: list[int] = field(default_factory=list)  # created documents (empty if discarded)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (document index, message)
