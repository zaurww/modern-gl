"""One posting as the table `postings` stores it (D159): the value object every path
goes through — a line typed in (`from_input`), a stored row (`from_row`), the row written
(`params`), the storno (`negated`), the snapshot for the audit trail (`as_dict`), and
what two documents are compared by (dataclass equality). A new column of a posting is
added here once: its field, and its name in `COLUMNS` in the table's order."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import ClassVar

from modern_gl.application.common import pad_subconto
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import KINDS, normalize_invoice
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row

# the columns that are not the posting's content: its key and its place in the document
KEY_COLUMNS = ("id", "company_id", "document_id", "line_no")


@dataclass(frozen=True)
class PostingRecord:
    """A posting as stored: amounts in minor units, subconto by column, the e-qaimə
    number normalized. Immutable; equal records are the same posting."""

    debit_account_id: int
    credit_account_id: int
    amount: int  # minor units
    dt_sc1: int | None
    dt_sc2: int | None
    dt_sc3: int | None
    ct_sc1: int | None
    ct_sc2: int | None
    ct_sc3: int | None
    memo: str
    currency_id: int | None
    currency_amount: int | None  # minor units of the currency; None without one
    invoice: str | None  # the e-qaimə (or customs declaration) number; None without one
    invoice_kind: str | None  # None: an e-qaimə or no number
    pays_vat: int  # 0/1

    # the content columns of `postings`, in the table's order
    COLUMNS: ClassVar[tuple[str, ...]] = (
        "debit_account_id",
        "credit_account_id",
        "amount",
        "dt_sc1",
        "dt_sc2",
        "dt_sc3",
        "ct_sc1",
        "ct_sc2",
        "ct_sc3",
        "memo",
        "currency_id",
        "currency_amount",
        "invoice",
        "invoice_kind",
        "pays_vat",
    )

    @classmethod
    def from_row(cls, row: Row) -> PostingRecord:
        """The record of a row read from `postings` (any row with its COLUMNS)."""
        return cls(*(row[column] for column in cls.COLUMNS))

    @classmethod
    def from_input(cls, p: PostingInput, line_no: int) -> PostingRecord:
        """A typed line as it will be stored; what is wrong names the line."""
        try:
            amount = to_minor(p.amount)
        except (TypeError, ValueError) as e:
            raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
        if amount == 0:
            raise ValidationError(tr("строка {line}: нулевая сумма", line=line_no))
        try:
            invoice = normalize_invoice(p.invoice)
        except ValidationError as e:
            raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
        currency_amount = None
        if p.currency_id is not None:
            try:
                currency_amount = to_minor(
                    p.currency_amount if p.currency_amount is not None else 0
                )
            except (TypeError, ValueError) as e:
                raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
        return cls(
            p.debit_account_id,
            p.credit_account_id,
            amount,
            *pad_subconto(p.debit_subconto, line_no),
            *pad_subconto(p.credit_subconto, line_no),
            p.memo,
            p.currency_id,
            currency_amount,
            invoice,
            invoice_kind(p) if invoice else None,
            int(p.pays_vat),
        )

    def params(self) -> tuple:
        """The values in the order of `COLUMNS`."""
        return tuple(getattr(self, column) for column in self.COLUMNS)

    def negated(self) -> PostingRecord:
        """The same posting with the amounts negated: a line of the red storno."""
        return replace(
            self,
            amount=-self.amount,
            currency_amount=None if self.currency_amount is None else -self.currency_amount,
        )

    def as_dict(self) -> dict:
        """The record as plain data for the audit trail's snapshot."""
        return asdict(self)


PLACEHOLDERS = ", ".join("?" for _ in PostingRecord.COLUMNS)
INSERT_POSTING = (
    f"INSERT INTO postings (company_id, document_id, line_no, {', '.join(PostingRecord.COLUMNS)}) "
    f"VALUES (?, ?, ?, {PLACEHOLDERS})"
)


def invoice_kind(p: PostingInput) -> str | None:
    """Stored kind of the posting's number: None for an e-qaimə (or no number)."""
    if p.invoice_kind not in KINDS:
        raise ValidationError(tr("неизвестный вид документа: {kind}", kind=p.invoice_kind))
    return p.invoice_kind or None if normalize_invoice(p.invoice) else None
