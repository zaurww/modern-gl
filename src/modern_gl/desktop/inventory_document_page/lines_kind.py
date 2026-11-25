"""«Куда» of a purchase line: to a warehouse (goods, an item), to an account (a service, a
fixed asset) or into the cost of goods (an expense of a batch: it waits on its account for
the batch that takes it, D211) — and making one of another. Which of the last two a line is
follows from its account: nothing else is kept."""

from __future__ import annotations

from PySide6.QtCore import Qt

from modern_gl.application.default_accounts import landed_cost_account
from modern_gl.desktop.inventory_document_page.columns import (
    GOODS,
    KIND,
    KIND_NAMES,
    LANDED,
    SERVICE,
)
from modern_gl.desktop.inventory_document_page.lines_spread import LineSpread
from modern_gl.desktop.purchase_label import purchase_label, purchase_short
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import receipt_documents, receipt_line_choices


class LineKinds(LineSpread):
    def _kind(self, row_index: int) -> int:
        if not self.is_service(row_index):
            return GOODS
        return LANDED if self.is_landed(row_index) else SERVICE

    def _kind_text(self, row_index: int) -> str:
        if self.rows[row_index].is_empty():
            return ""
        return tr(KIND_NAMES[self._kind(row_index)])

    def kind_cell_text(self, row_index: int, key: str) -> str:
        """«Куда» of the line, or — «К покупке» — the purchase its expense is for."""
        if key == KIND:
            return self._kind_text(row_index)
        return self.purchase_text(self.rows[row_index].for_document_id)

    def set_kind(self, row_index: int, kind: object) -> bool:
        """Another «Куда» picked. False: the line stays as it is — the same was picked, or
        goods were: an item is made by the page."""
        if kind not in KIND_NAMES or kind == self._kind(row_index):
            return False
        if kind == GOODS:
            self.goods_wanted.emit(row_index)
            return False
        if not self.is_service(row_index):
            self.make_service(row_index)
        row = self.rows[row_index]
        if kind == LANDED:
            row.expense_account_id = self._landed_account()
            row.expense_subconto = [None, None, None]
            row.expense_date = None  # it is no expense of a month: it waits for its batch
            self.spread_expense_account(row_index)
        elif row.expense_account_id in self.waiting_accounts:
            row.expense_account_id = None  # «Счёт»: another one is to be chosen
            row.for_document_id = None
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        return True

    def _landed_account(self) -> int:
        """Where the expenses of a batch wait; a chart without such an account gets one."""
        account_id = landed_cost_account(self.s.ledger, self.s.company_id)
        if account_id not in self.s.catalog.accounts:
            self.s.catalog.reload()
        self.waiting_accounts.add(account_id)
        return account_id

    def has_landed(self) -> bool:
        """An expense of a batch among the lines: «К покупке» is shown."""
        return any(self.is_landed(row) for row in range(len(self.rows)))

    def purchase_choices(self) -> list[tuple[int, str]]:
        """The purchases of goods an expense may be for, the newest first (read once);
        not the document's own."""
        if self._purchases is None:
            lines = receipt_line_choices(self.s.conn, self.s.company_id)
            documents = receipt_documents(lines)
            self._purchases = [(doc.document_id, purchase_label(doc)) for doc in documents]
            self._purchase_names = {doc.document_id: purchase_short(doc) for doc in documents}
        return [choice for choice in self._purchases if choice[0] != self.document_id]

    def purchase_text(self, document_id: int | None) -> str:
        """In the cell: the declaration's (e-qaimə's) number; the list says the rest."""
        if document_id is None:
            return ""
        self.purchase_choices()
        return self._purchase_names.get(document_id, "")

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
            row.for_document_id = None
        self.beginResetModel()
        self.endResetModel()
        self.changed.emit()
