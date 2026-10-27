"""An account chosen on one service line of a purchase goes to the others still without
one, and its subconto to the lines of that account where it is empty: ten lines of one
e-qaimə for one expense are typed once. What is filled already does not change."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase


class LineSpread(InventoryLinesBase):
    def spread_expense_account(self, row_index: int) -> None:
        """The line's account and subconto to the service lines without an account."""
        source = self.rows[row_index]
        if source.expense_account_id is None:
            return
        for index, row in enumerate(self.rows):
            if index != row_index and row.expense_account_id is None and self.is_service(index):
                row.expense_account_id = source.expense_account_id
                row.expense_subconto = list(source.expense_subconto)
        self._all_rows_changed()

    def spread_expense_subconto(self, row_index: int, position: int) -> None:
        """The line's subconto value to the lines of the same account where it is empty."""
        source = self.rows[row_index]
        value = source.expense_subconto[position]
        if source.expense_account_id is None or value is None:
            return
        for index, row in enumerate(self.rows):
            if (
                index != row_index
                and self.is_service(index)
                and row.expense_account_id == source.expense_account_id
                and row.expense_subconto[position] is None
            ):
                row.expense_subconto[position] = value
        self._all_rows_changed()

    def _all_rows_changed(self) -> None:
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )
