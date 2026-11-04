"""«Заполнить остатком…»: the balance of an account becomes the document's lines — a
debit balance on the credit side (written off from there), a credit one on the debit
side; the other side is the account chosen, or left for the lines."""

from __future__ import annotations

from fractions import Fraction

from modern_gl.application.balance_fill import BOOK_OF_LAYER, BalanceLine
from modern_gl.desktop.document_page.form import DocumentForm
from modern_gl.desktop.fill_balance_dialog import FillBalanceDialog
from modern_gl.desktop.postings import PostingRow
from modern_gl.desktop.widgets import edited_date
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import tr


def balance_row(line: BalanceLine, other_id: int | None) -> PostingRow:
    """The line that brings this balance to zero."""
    subconto = list(line.subconto)
    empty: list[int | None] = [None, None, None]
    cur = abs(line.currency_amount) if line.currency_amount is not None else None
    amount = abs(line.amount)
    if line.amount > 0 or (line.amount == 0 and (line.currency_amount or 0) > 0):
        debit, debit_sc, credit, credit_sc = other_id, empty, line.account_id, subconto
    else:
        debit, debit_sc, credit, credit_sc = line.account_id, subconto, other_id, empty
    return PostingRow(
        debit,
        debit_sc,
        credit,
        credit_sc,
        amount or None,
        currency_id=line.currency_id,
        currency_amount=cur,
        rate=Fraction(amount, cur) if cur and amount else None,
        rate_auto=False,  # the balance's own manat, not the day's rate
    )


class FillPart(DocumentForm):
    def fill_from_balance(self) -> None:
        if self.model.read_only:
            return
        self.table.setFocus()  # commits an open cell editor
        layer = self.layer.currentData()
        dialog = FillBalanceDialog(
            self.s,
            iso_date(edited_date(self.date)),
            BOOK_OF_LAYER.get(layer, BOOK_OF_LAYER["common"]),
            self.doc_id,
            self,
        )
        if dialog.exec():
            self.add_balance(dialog.lines, dialog.other_id)

    def add_balance(self, lines: list[BalanceLine], other_id: int | None) -> None:
        """The lines after those already typed (an empty grid — instead of its blank row)."""
        rows = [balance_row(ln, other_id) for ln in lines]
        kept = [r for r in self.model.rows if not r.is_empty()]
        self.model.beginResetModel()
        self.model.rows = kept + rows or [PostingRow()]
        self.model.endResetModel()
        self.model.changed.emit()
        self.s.notify(tr("Добавлено строк: {n}", n=len(rows)))
