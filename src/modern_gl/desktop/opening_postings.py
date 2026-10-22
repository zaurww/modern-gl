"""The opening balances as a postings table: one line per balance, «Дебет» or «Кредит»,
the counter-account is always the opening account."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import cast

from PySide6.QtCore import Qt

from modern_gl.application.ledger import PostingInput, opening_posting
from modern_gl.application.queries import PostingData
from modern_gl.desktop.postings import (
    AMOUNT,
    CT,
    DT,
    HEADER_FIELDS,
    HEADERS,
    INVOICE,
    MEMO,
    PostingRow,
    PostingsModel,
    header_columns,
    header_names,
)
from modern_gl.domain.accounts import DEBIT_NORMAL
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr

CREDIT_AMOUNT = len(HEADERS)  # the second amount column, after "Дебет" (AMOUNT)
OPENING_FIELDS = [
    (header_names("Счёт", "Код"), DT),
    (header_names("Дебет", "Дт", "Сальдо Дт", "Сальдо дебет"), AMOUNT),
    (header_names("Кредит", "Кт", "Сальдо Кт", "Сальдо кредит"), CREDIT_AMOUNT),
    *((names, col) for names, col in HEADER_FIELDS if col not in (DT, CT, AMOUNT)),
]


@dataclass
class OpeningRow(PostingRow):
    """A balance: the account sits in the debit slot, the counter-account "00" in the
    credit slot; `on_credit` tells which column the amount is shown in and which side
    of the account it lands on."""

    on_credit: bool = False

    def is_empty(self) -> bool:
        return (
            self.debit is None
            and self.amount is None
            and self.currency_amount is None
            and not self.memo.strip()
            and not self.invoice
        )


class OpeningPostingsModel(PostingsModel):
    """One balance per line: account, subconto, then the amount in "Дебет" or "Кредит"."""

    def __init__(self, catalog, control_account: int) -> None:
        self.control_account = control_account
        super().__init__(catalog, inherit_invoices=False)
        self.rows = [self._blank()]

    def _blank(self) -> OpeningRow:
        return OpeningRow(credit=self.control_account)

    def row_from(self, p: PostingData) -> OpeningRow:
        row = PostingRow.from_data(p)
        on_credit = p.debit_account_id == self.control_account
        account, sc = (row.credit, row.credit_sc) if on_credit else (row.debit, row.debit_sc)
        fields = asdict(row) | {
            "debit": account,
            "debit_sc": sc,
            "credit": self.control_account,
            "credit_sc": [None, None, None],
        }
        return OpeningRow(**fields, on_credit=on_credit)

    # ---- columns ---------------------------------------------------------------------

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(HEADERS) + 1

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        titles = {DT: "Счёт", AMOUNT: "Дебет", CREDIT_AMOUNT: "Кредит"}
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and section in titles
        ):
            return tr(titles[section])
        return super().headerData(section, orientation, role)

    def column_order(self) -> list[int]:
        return [*range(AMOUNT + 1), CREDIT_AMOUNT, MEMO, INVOICE]

    def is_number(self, col: int) -> bool:
        return col == CREDIT_AMOUNT or super().is_number(col)

    def header_columns(self, cells: list[str]) -> list[int | None] | None:
        return header_columns(cells, OPENING_FIELDS)

    def applies(self, row: int, col: int) -> bool:
        return col == CREDIT_AMOUNT or super().applies(row, col)

    # ---- values ----------------------------------------------------------------------

    def _text(self, row: int, col: int, display: bool) -> str:
        if col in (AMOUNT, CREDIT_AMOUNT):
            if (col == CREDIT_AMOUNT) != cast(OpeningRow, self.rows[row]).on_credit:
                return ""
            col = AMOUNT
        return super()._text(row, col, display)

    def parse(self, row: int, col: int, text: str):
        return super().parse(row, AMOUNT if col == CREDIT_AMOUNT else col, text)

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        row, col = index.row(), index.column()
        r = cast(OpeningRow, self.rows[row])
        if col in (AMOUNT, CREDIT_AMOUNT):
            on_credit = col == CREDIT_AMOUNT
            if value is None and on_credit != r.on_credit:
                return True  # clearing the empty column leaves the other one alone
            r.on_credit = on_credit
            super().setData(self.index(row, AMOUNT), value, role)
            self._row_changed(row)
            return True
        had_amount = r.amount is not None or r.currency_amount is not None
        done = super().setData(index, value, role)
        if col == DT and r.debit is not None and not had_amount:
            account = self.catalog.accounts[r.debit]
            # a new line takes the account's normal side: 60 or 80 in "Кредит", 02 too
            credit_normal = account.account_class not in (None, *DEBIT_NORMAL)
            r.on_credit = account.account_class is not None and credit_normal != account.contra
            self._row_changed(row)
        return done

    def totals(self) -> tuple[int, int]:
        """Debit and credit balances entered so far."""
        rows = cast(list[OpeningRow], self.rows)
        debit = sum(r.amount or 0 for r in rows if not r.on_credit)
        credit = sum(r.amount or 0 for r in rows if r.on_credit)
        return debit, credit

    # ---- rows ------------------------------------------------------------------------

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        return super().insert_row(at, row or self._blank())

    def duplicate_row(self, i: int) -> int:
        src = cast(OpeningRow, self.rows[i])
        return self.insert_row(
            i + 1, replace(src, debit_sc=list(src.debit_sc), credit_sc=[None, None, None])
        )

    def to_inputs(self) -> list[PostingInput]:
        """A debit balance is "Дт account / Кт 00", a credit one "Дт 00 / Кт account"."""
        lines: list[PostingRow] = []
        sides: list[bool] = []
        for n, r in enumerate(cast(list[OpeningRow], self.rows), start=1):
            if r.is_empty():
                lines.append(PostingRow())  # skipped, but keeps the line numbers
                continue
            if r.debit is None:
                raise ValidationError(tr("строка {line}: не указан счёт", line=n))
            lines.append(replace(r, debit_sc=list(r.debit_sc), credit_sc=[None, None, None]))
            sides.append(r.on_credit)
        rows = self.rows
        self.rows = lines
        try:
            typed = super().to_inputs() if sides else []
        finally:
            self.rows = rows
        return [opening_posting(p, on_credit) for p, on_credit in zip(typed, sides, strict=True)]
