"""One value for many lines of a purchase: an account chosen on one service line goes to
the others still without one, a cost item to the lines of that account without one (ten
lines of one e-qaimə for one expense are typed once);
a value picked with several lines selected goes to all of them; a fixed asset (an
intangible) of each line is its own element, named by the line (D172)."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.columns import (
    ESC_KEYS,
    ITEM,
    KIND,
    LIST_KEYS,
    SUBCONTO_KEYS,
)
from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase

# directories where each line is an element of its own: an asset is not shared by lines
PER_LINE_KINDS = {"fixed_asset", "intangible"}
# cells whose value can be set on several selected lines at once
MANY_KEYS = LIST_KEYS - {ITEM, KIND}


class LineSpread(InventoryLinesBase):
    def spread_expense_account(self, row_index: int) -> None:
        """The line's account to the service lines without an account."""
        source = self.rows[row_index]
        if source.expense_account_id is None:
            return
        for index, row in enumerate(self.rows):
            if index != row_index and row.expense_account_id is None and self.is_service(index):
                row.expense_account_id = source.expense_account_id
        self._all_rows_changed()

    def spread_expense_subconto(self, row_index: int, position: int) -> None:
        """A category (a cost item) of the line to the lines of the same account where it
        is empty; an asset (`PER_LINE_KINDS`) is each line's own and is not spread."""
        source = self.rows[row_index]
        value = source.expense_subconto[position]
        key = f"esc{position + 1}"
        if source.expense_account_id is None or value is None or self.is_per_line(row_index, key):
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

    def set_on_rows(self, rows: list[int], key: str, value: object, like: int) -> None:
        """The value just set on line `like` to the other `rows` that take it: a subconto
        only where the column is the same directory."""
        if key not in MANY_KEYS:
            return
        column = self.columns.index(key)
        kind = self.kind_at(like, key)
        for row in rows:
            if row == like or not self.applies(row, key):
                continue
            if key in SUBCONTO_KEYS and self.kind_at(row, key) != kind:
                continue
            self.setData(self.index(row, column), value)

    def is_per_line(self, row_index: int, key: str) -> bool:
        """The cell is a fixed asset (an intangible) of the line: an element of its own."""
        kind = self.kind_at(row_index, key) if key in ESC_KEYS else None
        return kind is not None and self.s.catalog.kind_codes.get(kind) in PER_LINE_KINDS

    def lines_without_object(self) -> list[tuple[int, str, str]]:
        """(row, line name, column key) of the service lines whose fixed asset (intangible)
        is not chosen yet."""
        found = []
        for row_index, row in enumerate(self.rows):
            if not self.is_service(row_index):
                continue
            for key in sorted(ESC_KEYS):
                position = int(key[-1]) - 1
                if self.is_per_line(row_index, key) and row.expense_subconto[position] is None:
                    found.append((row_index, row.memo.strip(), key))
        return [(r, name, key) for r, name, key in found if name]

    def _all_rows_changed(self) -> None:
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )
