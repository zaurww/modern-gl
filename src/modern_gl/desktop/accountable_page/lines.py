"""The lines of an advance report as a postings table (as in 1C): what the money went on —
the account, its subconto, the amount and the receipt; the other side is always the
accountable account with the employee, so it is not shown."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt

from modern_gl.application.accountable import AdvanceLine
from modern_gl.desktop.postings import AMOUNT, CT, DT, MEMO, PostingRow, PostingsModel
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr

COLUMNS = [*range(DT, CT), AMOUNT, MEMO]  # the account, its three subconto, amount, receipt


@dataclass
class AdvanceRow(PostingRow):
    """A line: the account in the debit slot; the accountable account sits in the credit
    slot only so the table's rules work — an empty line is one with nothing typed."""

    def is_empty(self) -> bool:
        return self.debit is None and self.amount is None and not self.memo.strip()


class AdvanceLinesModel(PostingsModel):
    def __init__(self, catalog, account_id: int | None) -> None:
        self.control = account_id
        super().__init__(catalog, inherit_invoices=False)
        self.rows = [self._blank()]

    def _blank(self) -> AdvanceRow:
        return AdvanceRow(credit=self.control)

    def column_order(self) -> list[int]:
        return COLUMNS

    def applies(self, row: int, col: int) -> bool:
        return col in COLUMNS and super().applies(row, col)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        titles = {DT: tr("Счёт"), MEMO: tr("Документ, содержание")}
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and section in titles
        ):
            return titles[section]
        return super().headerData(section, orientation, role)

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        return super().insert_row(at, row or self._blank())

    def duplicate_row(self, i: int) -> int:
        src = self.rows[i]
        return self.insert_row(
            i + 1,
            AdvanceRow(src.debit, list(src.debit_sc), self.control, amount=src.amount),
        )

    def set_lines(self, lines: list[AdvanceLine]) -> None:
        self.beginResetModel()
        self.rows = [
            AdvanceRow(
                line.account_id,
                [*line.subconto, None, None, None][:3],
                self.control,
                amount=line.amount or None,
                memo=line.memo,
            )
            for line in lines
        ] or [self._blank()]
        self.endResetModel()
        self.changed.emit()

    def lines(self) -> list[AdvanceLine]:
        """What was typed, an empty line left out; a line with an amount needs its account
        only when posted (a draft keeps it as it is)."""
        return [
            AdvanceLine(r.debit, r.amount or 0, tuple(r.debit_sc), r.memo.strip())
            for r in self.rows
            if not r.is_empty()
        ]

    def spent(self) -> int:
        return sum(r.amount or 0 for r in self.rows if not r.is_empty())

    def check(self) -> None:
        """A negative amount is not a spending."""
        for n, r in enumerate(self.rows, start=1):
            if (r.amount or 0) < 0:
                raise ValidationError(tr("строка {line}: сумма меньше нуля", line=n))
