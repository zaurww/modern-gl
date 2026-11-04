"""The state of a GL document's lines and what each cell is: which cells a line has (its
accounts' subconto, currency, e-qaimə), whose a contract is, the columns in order."""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.postings.columns import (
    ALIGN_LEFT,
    ALIGN_RIGHT,
    AMOUNT,
    CURRENCY,
    CURRENCY_COLUMNS,
    HEADERS,
    INVOICE,
    NUMBER_COLUMNS,
    QUANTITY,
    PostingRow,
    column_role,
)
from modern_gl.domain.currency import (
    CURRENCY_ONLY,
)
from modern_gl.i18n import tr


class PostingsBase(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        catalog: Catalog,
        rows: list[PostingRow] | None = None,
        read_only: bool = False,
        formulas: bool = False,
        inherit_invoices: bool = True,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.rows = rows or [PostingRow()]
        self.read_only = read_only
        self.formulas = formulas  # template editing: the amount column holds formulas
        self.inherit_invoices = inherit_invoices
        # currency id -> manat per unit on the document date (set by the document page)
        self.rate_for: Callable[[int], Fraction | None] = lambda _currency_id: None

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return tr(HEADERS[section]) if HEADERS[section] else ""
            return str(section + 1)
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return ALIGN_RIGHT if self.is_number(section) else ALIGN_LEFT
        return None

    def column_order(self) -> list[int]:
        """Columns in the order they are shown, typed and pasted: the quantity before
        the amount."""
        order = [c for c in range(self.columnCount()) if c != QUANTITY]
        return [*order[: order.index(AMOUNT)], QUANTITY, *order[order.index(AMOUNT) :]]

    def is_number(self, col: int) -> bool:
        return col in NUMBER_COLUMNS

    def _currency_modes(self, row: int) -> list[int]:
        r = self.rows[row]
        if self.formulas:
            return []
        modes = [self.catalog.accounts[a].currency for a in (r.debit, r.credit) if a is not None]
        return [m for m in modes if m]

    def is_currency(self, row: int) -> bool:
        """The line hits a currency account, so it may have a currency and an amount in it."""
        return bool(self._currency_modes(row))

    def currency_required(self, row: int) -> bool:
        """The line hits an account kept only in currency (52): manat alone won't do."""
        return CURRENCY_ONLY in self._currency_modes(row)

    def in_currency(self, row: int) -> bool:
        """The line is (or has to be) in a currency: its currency cells are in use.
        A line on 60 / 62 with a local partner stays in manat and shows none of them."""
        return self.currency_required(row) or (
            self.is_currency(row) and self.rows[row].currency_id is not None
        )

    def counts(self, row: int) -> bool:
        """The line hits a counted account (01, 10, 12…): it may say how many."""
        r = self.rows[row]
        return not self.formulas and bool({r.debit, r.credit} & self.catalog.counted)

    def takes_invoice(self, row: int) -> bool:
        """The line is on a settlement or ƏDV account: it may name its e-qaimə."""
        r = self.rows[row]
        return not self.formulas and (
            self.catalog.takes_invoice(r.debit) or self.catalog.takes_invoice(r.credit)
        )

    def kind_at(self, row: int, col: int) -> int | None:
        """Subconto kind required at this cell, or None if the cell doesn't apply."""
        side, pos = column_role(col)
        if pos is None:
            return None
        account_id = getattr(self.rows[row], side)
        if account_id is None:
            return None
        return self.catalog.accounts[account_id].sc_kinds[pos - 1]

    def applies(self, row: int, col: int) -> bool:
        if col == CURRENCY:
            return self.is_currency(row)
        if col in CURRENCY_COLUMNS:
            return self.in_currency(row)
        if col == INVOICE:
            return self.takes_invoice(row)
        if col == QUANTITY:
            return self.counts(row)
        _, pos = column_role(col)
        return pos is None or self.kind_at(row, col) is not None

    def owner_at(self, row: int, col: int) -> int | None:
        """The counterparty chosen on the line for a contract cell (None: any contract)."""
        side, pos = column_role(col)
        account_id = getattr(self.rows[row], side) if pos is not None else None
        if account_id is None or pos is None:
            return None
        account = self.catalog.accounts[account_id]
        return self.catalog.owner_in(account, getattr(self.rows[row], f"{side}_sc"), pos - 1)

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row or PostingRow())
        self.endInsertRows()
        self.changed.emit()
        return at
