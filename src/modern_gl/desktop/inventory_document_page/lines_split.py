"""Splitting a line: in two by a quantity or an amount («Разделить строку»), or over the
months its expense belongs to (D65) — the sum of the parts is the line as it was."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.columns import InventoryGridRow
from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import round_ratio
from modern_gl.i18n import tr


def shares(total: int | None, parts: int) -> list[int | None]:
    """`total` split evenly into `parts`: the remainder of kopecks goes to the last."""
    if total is None:
        return [None] * parts
    base, rest = divmod(total, parts)
    return [*([base] * (parts - 1)), base + rest]


def portion(total: int | None, part: int, whole: int) -> int | None:
    """The share of `total` that `part` of `whole` is, rounded half away from zero."""
    return None if total is None else round_ratio(total * part, whole)


class LineSplits(InventoryLinesBase):
    def split_by_months(self, row_index: int, months: list[str]) -> list[int]:
        """The line becomes one line per month (each month's last day), the amount, VAT
        and currency amount divided evenly, the remainder of kopecks in the last month.
        The quantity stays only when it divides without a remainder. Returns the rows."""
        if len(months) < 2:
            raise ValidationError(tr("выберите хотя бы два месяца"))
        row = self.rows[row_index]
        parts = len(months)
        amounts = shares(row.amount, parts)
        vats = shares(row.vat_amount, parts)
        currency = shares(row.currency_amount, parts)
        quantity = (
            row.quantity // parts
            if row.quantity is not None and row.quantity % parts == 0
            else None
        )
        rows = []
        for i, month in enumerate(months):
            part = row if i == 0 else row.copy()
            part.amount, part.vat_amount, part.currency_amount = amounts[i], vats[i], currency[i]
            part.quantity = quantity
            part.expense_date = month
            if i:
                self.insert_row(row_index + i, part)
            rows.append(row_index + i)
        self._row_changed(row_index)
        return rows

    def split_row(
        self, row_index: int, *, quantity: int | None = None, amount: int | None = None
    ) -> int:
        """The line in two: `quantity` (goods) or `amount` (a service) goes to a new line
        below, the rest stays; VAT and the currency amount follow in proportion. Returns the
        new row."""
        row = self.rows[row_index]
        moved = row.copy()
        if quantity is not None:
            whole = row.quantity or 0
            if not 0 < quantity < whole:
                raise ValidationError(
                    tr("количество во вторую строку — больше нуля и меньше всего")
                )
            moved.quantity, row.quantity = quantity, whole - quantity
            for field in ("amount", "vat_amount", "currency_amount"):
                self._move_share(row, moved, field, quantity, whole)
        else:
            whole = row.amount or 0
            if amount is None or not 0 < amount < whole:
                raise ValidationError(tr("сумма во вторую строку — больше нуля и меньше всей"))
            moved.amount, row.amount = amount, whole - amount
            for field in ("vat_amount", "currency_amount"):
                self._move_share(row, moved, field, amount, whole)
            row.quantity = moved.quantity = None
        new_row = self.insert_row(row_index + 1, moved)
        self._row_changed(row_index)
        return new_row

    @staticmethod
    def _move_share(row: InventoryGridRow, moved: InventoryGridRow, field: str, part, whole):
        total = getattr(row, field)
        share = portion(total, part, whole)
        setattr(moved, field, share)
        setattr(row, field, None if total is None or share is None else total - share)

    def _row_changed(self, row_index: int) -> None:
        self.dataChanged.emit(
            self.index(row_index, 0), self.index(row_index, len(self.columns) - 1)
        )
        self.changed.emit()
