"""«Куда» of a purchase line: to a warehouse (goods, an item) or to an account (a service,
a fixed asset) — and making one of the other."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.columns import GOODS, KIND_NAMES, SERVICE
from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase
from modern_gl.i18n import tr


class LineKinds(InventoryLinesBase):
    def _kind(self, row_index: int) -> int:
        return SERVICE if self.is_service(row_index) else GOODS

    def _kind_text(self, row_index: int) -> str:
        if self.rows[row_index].is_empty():
            return ""
        return tr(KIND_NAMES[self._kind(row_index)])

    def make_service(self, row_index: int) -> None:
        """Goods made a service: the line keeps what it is as its text and goes to an
        account — the one this service had the last time, if it was bought before."""
        row = self.rows[row_index]
        item = self.items.get(row.item_id) if row.item_id is not None else None
        row.memo = row.memo.strip() or (item.label if item else "")
        row.item_id = row.warehouse_id = None
        self._remember_expense(row_index)

    def make_goods(self, items: dict[int, int], warehouse_id: int | None) -> None:
        """Service lines made goods: row -> its item, from (to) `warehouse_id`; the
        account the service went to is dropped."""
        self.refresh_choices()
        for row_index, item_id in items.items():
            row = self.rows[row_index]
            row.item_id = item_id
            row.warehouse_id = row.warehouse_id or warehouse_id
            row.expense_account_id, row.expense_date = None, None
            row.expense_subconto = [None, None, None]
        self.beginResetModel()
        self.endResetModel()
        self.changed.emit()
