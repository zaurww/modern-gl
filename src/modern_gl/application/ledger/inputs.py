"""Inputs of the ledger use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.domain.quantity import from_quantity
from modern_gl.i18n import N_, tr

DEFAULT_LAYERS = (
    ("common", "Общий учёт"),
    ("ifrs_adj", N_("Корректировки МСФО")),
    ("tax_adj", N_("Налоговые корректировки")),
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
    invoice_kind: str = ""  # domain.invoice: "" an e-qaimə, "customs" a customs declaration
    # a payment from a bank account to the supplier's ƏDV deposit: it pays the ƏDV (D145)
    pays_vat: bool = False
    # how many (a counted account — 01, 10, 12…, D199): "3", "0.5"; None — not said
    quantity: str | int | Decimal | None = None


class TypedLine(Protocol):
    """A posting as a form or the quick line holds it: amounts in minor units."""

    @property
    def debit(self) -> int | None:
        """The debit account id; None while not chosen."""
        ...

    @property
    def credit(self) -> int | None:
        """The credit account id; None while not chosen."""
        ...

    @property
    def amount(self) -> int | None:
        """The amount in minor units (kopecks); None while not typed."""
        ...

    @property
    def debit_sc(self) -> Sequence[int | None]:
        """Debit subconto by position (1..3); None where empty."""
        ...

    @property
    def credit_sc(self) -> Sequence[int | None]:
        """Credit subconto by position (1..3); None where empty."""
        ...

    @property
    def memo(self) -> str:
        """The posting's text as typed (trimmed by `typed_posting`)."""
        ...

    @property
    def currency_id(self) -> int | None:
        """The currency of the posting; None — in manat."""
        ...

    @property
    def currency_amount(self) -> int | None:
        """The amount in the currency, minor units; None without a currency."""
        ...

    @property
    def invoice(self) -> str:
        """The e-qaimə number typed; "" — none."""
        ...


def typed_posting(
    n: int,
    line: TypedLine,
    *,
    currency: bool = True,
    invoice: bool = True,
    invoice_kind: str = "",
    pays_vat: bool = False,
    quantity: int | None = None,
) -> PostingInput:
    """Line `n` of a form as the ledger's input; `currency` / `invoice` — whether its
    accounts keep them (else what was typed there is not passed on)."""
    if line.debit is None:
        raise ValidationError(tr("строка {line}: не указан счёт дебета", line=n))
    if line.credit is None:
        raise ValidationError(tr("строка {line}: не указан счёт кредита", line=n))
    if line.amount is None:
        raise ValidationError(tr("строка {line}: не указана сумма", line=n))
    in_currency = currency and line.currency_id is not None
    number = line.invoice if invoice else ""
    return PostingInput(
        line.debit,
        line.credit,
        from_minor(line.amount),
        tuple(line.debit_sc),
        tuple(line.credit_sc),
        line.memo.strip(),
        line.currency_id if in_currency else None,
        from_minor(line.currency_amount or 0) if in_currency else None,
        number,
        invoice_kind if number else "",
        pays_vat,
        from_quantity(quantity) if quantity else None,
    )


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
    """One document to import (`import_documents`): postings in manat, as PostingInput."""

    doc_date: date | str
    postings: Sequence[PostingInput]
    memo: str = ""
    layer: str = "common"
    external_id: str = ""  # its id in the program it came from (with `source`, D130)
    reverses: str = ""  # a red storno of the document of this external id (no postings)


@dataclass
class ImportOutcome:
    """What `import_documents` did: created ids, problems by document, or ones there already."""

    ids: list[int] = field(default_factory=list[int])  # created documents (empty if discarded)
    errors: list[tuple[int, str]] = field(
        default_factory=list[tuple[int, str]]
    )  # (document index, message)
    # (document index, its id): imported before from the same source, left as it is
    existing: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
