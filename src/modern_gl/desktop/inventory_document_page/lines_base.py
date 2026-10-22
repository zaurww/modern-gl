"""The state of a warehouse document's lines and what each cell is: the columns of the
document type, the lists a cell offers, which cells a line has and which are typed."""

from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Signal,
)

from modern_gl.application.inventory import (
    INCOMING_TYPES,
    Inventory,
)
from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    ESC1,
    ESC2,
    ESC3,
    ESC_KEYS,
    EXPENSE,
    ITEM,
    MEMO,
    PRICE,
    QUANTITY,
    SALE1,
    SALE2,
    SALE3,
    SALE_KEYS,
    SC1,
    SC2,
    SC3,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    VAT_DOCUMENTS,
    WAREHOUSE,
    InventoryGridRow,
)
from modern_gl.desktop.session import Session
from modern_gl.reporting.inventory import (
    Choice,
    ItemChoice,
    item_choices,
    warehouse_choices,
)


def sale_kinds(session: Session) -> list[int]:
    """The subconto kinds a sale line is asked for (`Inventory.sale_kinds`, D61)."""
    return Inventory(session.conn, actor=session.ledger.actor).sale_kinds(session.company_id)


def by_sale_kinds(catalog, kinds: list[int], values) -> list[int | None]:
    """Stored sale subconto values in the order of the columns of `kinds`."""
    result: list[int | None] = [None, None, None]
    for value in values:
        if value is not None and catalog.value(value).kind_id in kinds:
            result[kinds.index(catalog.value(value).kind_id)] = value
    return result


class InventoryLinesBase(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        session: Session,
        doc_type: str,
        rows: list[InventoryGridRow] | None = None,
        read_only: bool = False,
        vat_rate: int | None = None,
        incoming_account: int | None = None,
    ) -> None:
        super().__init__()
        self.incoming_account = incoming_account  # a mədaxil's: its reason's account (D91)
        self.s = session
        self.doc_type = doc_type
        self.read_only = read_only
        self.vat_rate = vat_rate if doc_type in VAT_DOCUMENTS else None
        self.rate: Fraction | None = None  # a receipt in a currency: manat per unit
        self.currency_code = ""
        self.items = self._items()
        self.warehouses = self._warehouses()
        self.has_currency = False
        # the kinds a sale line is asked for (D61), one column each
        self.sale_kinds = sale_kinds(session) if doc_type == "sale" else []
        self.stock_only = session.stock_only  # a warehouse only (D90)
        self.rows = rows or [self.default_row()]
        # a company kept as a warehouse only (D90): the offset account is put in by itself
        # and not shown — unless the chart has none to put in
        self.accounts_hidden = self._accounts_hidden()
        if doc_type == "transfer":
            self.columns = [
                ITEM,
                WAREHOUSE,
                TO_WAREHOUSE,
                QUANTITY,
                UNIT,
                PRICE,
                AMOUNT,
                MEMO,
            ]
        elif doc_type == "landed_cost":
            self.columns = [ITEM, WAREHOUSE, QUANTITY, UNIT, AMOUNT, MEMO]
        else:
            self.columns = [
                ITEM,
                WAREHOUSE,
                QUANTITY,
                UNIT,
                PRICE,
                *([CURRENCY_AMOUNT] if doc_type == "receipt" else []),
                AMOUNT,
                *([VAT] if doc_type in VAT_DOCUMENTS else []),
                *([EXPENSE, ESC1, ESC2, ESC3] if doc_type == "receipt" else []),
                *([SALE1, SALE2, SALE3] if doc_type == "sale" else []),
                ACCOUNT,
                SC1,
                SC2,
                SC3,
                MEMO,
            ]

    def _items(self) -> dict[int, ItemChoice]:
        return {c.id: c for c in item_choices(self.s.conn, self.s.company_id)}

    def _warehouses(self) -> dict[int, Choice]:
        return {c.id: c for c in warehouse_choices(self.s.conn, self.s.company_id)}

    def refresh_choices(self) -> None:
        self.items = self._items()
        self.warehouses = self._warehouses()

    def choices(self, row_index: int, key: str) -> list[tuple[int, str]]:
        """(id, label) offered in a list cell."""
        if key == ITEM:
            return [(item.id, item.label) for item in self.items.values()]
        if key in {WAREHOUSE, TO_WAREHOUSE}:
            return [(warehouse.id, warehouse.label) for warehouse in self.warehouses.values()]
        if key == ACCOUNT:
            return [(account.id, account.label) for account in self.s.catalog.leaf_accounts]
        if key == EXPENSE:  # goods come to a stock account through the warehouse only
            catalog = self.s.catalog
            return [
                (account.id, account.label)
                for account in catalog.leaf_accounts
                if not catalog.is_stock_account(account.id)
            ]
        kind_id = self.kind_at(row_index, key)
        owner = self.owner_at(row_index, key)
        return (
            [(value.id, value.label) for value in self.s.catalog.values(kind_id, owner)]
            if kind_id
            else []
        )

    def owner_at(self, row_index: int, key: str) -> int | None:
        """The counterparty chosen on the line, for its contracts (None: any contract)."""
        account_id = self._account_of(self.rows[row_index], key)
        if key not in SUBCONTO_KEYS or key in SALE_KEYS or account_id is None:
            return None
        account = self.s.catalog.accounts[account_id]
        subconto = self._subconto_of(self.rows[row_index], key)
        return self.s.catalog.owner_in(account, subconto, int(key[-1]) - 1)

    @staticmethod
    def _account_of(row: InventoryGridRow, key: str) -> int | None:
        """The account a subconto cell belongs to: the expense account's or the offset's."""
        return row.expense_account_id if key in ESC_KEYS | {EXPENSE} else row.offset_account_id

    @staticmethod
    def _subconto_of(row: InventoryGridRow, key: str) -> list[int | None]:
        if key in SALE_KEYS:
            return row.sale_subconto
        return row.expense_subconto if key in ESC_KEYS else row.offset_subconto

    def default_row(self) -> InventoryGridRow:
        if self.doc_type == "incoming":
            return InventoryGridRow(offset_account_id=self.incoming_account)
        codes = [{"opening": "60", "receipt": "60", "sale": "62"}.get(self.doc_type, "46")]
        if self.doc_type == "opening" and self.stock_only:
            codes = ["88", "84", *codes]  # unseen (D90): retained earnings, not a supplier
        account = next(filter(None, map(self._leaf_by_code, codes)), None)
        if account is None or self.doc_type in {"transfer", "landed_cost"}:
            return InventoryGridRow()
        # Subconto (counterparty, contract) stay empty: a guessed value would post silently.
        return InventoryGridRow(offset_account_id=account.id)

    def _accounts_hidden(self) -> bool:
        return (
            self.stock_only
            and self.doc_type not in {"transfer", "landed_cost"}
            and self.default_row().offset_account_id is not None
        )

    def set_incoming_account(self, account_id: int | None) -> None:
        """Another reason of a mədaxil: the lines still on the previous reason's account
        (or on none) go to the new one, without the old account's subconto."""
        old, self.incoming_account = self.incoming_account, account_id
        for row in self.rows:
            if row.offset_account_id in (old, None) and row.offset_account_id != account_id:
                row.offset_account_id = account_id
                row.offset_subconto = [None, None, None]
        self.accounts_hidden = self._accounts_hidden()
        self.beginResetModel()
        self.endResetModel()
        self.changed.emit()

    def _leaf_by_code(self, code: str):
        """The account of the code, or the first under it when it is a group (60 → 60.1)."""
        account = self.s.catalog.by_code.get(code)
        if account is not None and account.is_group:
            account = next(
                (
                    candidate
                    for candidate in self.s.catalog.leaf_accounts
                    if candidate.code.startswith(f"{code}.")
                ),
                None,
            )
        return account

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def key(self, index: QModelIndex) -> str:
        return self.columns[index.column()]

    def sale_kind(self, key: str) -> int | None:
        """The directory of a sale subconto column (None: no such column)."""
        position = int(key[-1]) - 1
        return self.sale_kinds[position] if position < len(self.sale_kinds) else None

    def kind_at(self, row_index: int, key: str) -> int | None:
        if key not in SUBCONTO_KEYS:
            return None
        if key in SALE_KEYS:
            return self.sale_kind(key)
        account_id = self._account_of(self.rows[row_index], key)
        if account_id is None:
            return None
        return self.s.catalog.accounts[account_id].sc_kinds[int(key[-1]) - 1]

    def has_goods(self) -> bool:
        """A purchase or sale of services only has no warehouse and unit columns; any
        other document, or one not begun yet, has them."""
        if self.doc_type not in {"sale", "receipt"}:
            return True
        lines = [i for i, row in enumerate(self.rows) if not row.is_empty()]
        return not lines or not all(self.is_service(i) for i in lines)

    def applies(self, row: int, key: str) -> bool:
        if key in {WAREHOUSE, UNIT} and self.is_service(row):
            return False
        if key in ESC_KEYS | {EXPENSE} and not self.is_service(row):
            return False
        if key in SALE_KEYS:
            return self._takes_sale(self.rows[row], key)
        return key not in SUBCONTO_KEYS or self.kind_at(row, key) is not None

    def _takes_sale(self, row: InventoryGridRow, key: str) -> bool:
        """The line is asked for the sale subconto of the column: a kind of the customer's
        account comes from the customer."""
        kind_id = self.sale_kind(key)
        account_id = row.offset_account_id
        customer = self.s.catalog.accounts[account_id].sc_kinds if account_id else ()
        return kind_id is not None and kind_id not in customer

    def is_service(self, row_index: int) -> bool:
        """A sale or receipt line without an item: a service (a fixed asset, an expense
        bought), from or to no warehouse. An empty new line is not one yet: it starts as goods."""
        row = self.rows[row_index]
        return self.doc_type in {"sale", "receipt"} and row.item_id is None and not row.is_empty()

    def has_expenses(self) -> bool:
        """A receipt with a line without an item shows the expense account columns."""
        return self.doc_type == "receipt" and any(
            row.item_id is None and not row.is_empty() for row in self.rows
        )

    def expense_positions(self) -> set[int]:
        """The subconto positions (1-3) the expense accounts of the lines have."""
        return {
            position
            for row in self.rows
            if row.item_id is None and row.expense_account_id is not None
            for position, kind in enumerate(
                self.s.catalog.accounts[row.expense_account_id].sc_kinds, 1
            )
            if kind is not None
        }

    def editable(self, key: str) -> bool:
        if key in {UNIT}:
            return False
        if key in {PRICE, AMOUNT} and self.doc_type not in {*INCOMING_TYPES, "sale"}:
            return False
        if key == VAT and self.doc_type not in VAT_DOCUMENTS:
            return False
        if key == CURRENCY_AMOUNT:  # in a currency the manat amount follows from the rate
            return self.rate is not None
        if key == AMOUNT and self.rate is not None:
            return False
        return self.doc_type != "landed_cost"

    def insert_row(self, at: int | None = None, row: InventoryGridRow | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row or self.default_row())
        self.endInsertRows()
        self.changed.emit()
        return at

    # ---- made by the model; each part may call it ------------------------------------

    def _edit_value(self, row_index: int, key: str):
        raise NotImplementedError

    def _display_text(self, row_index: int, key: str) -> str:
        raise NotImplementedError
