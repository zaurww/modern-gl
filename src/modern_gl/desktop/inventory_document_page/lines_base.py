"""The state of a warehouse document's lines and what each cell is: the columns of the
document type, the lists a cell offers, which cells a line has and which are typed."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Signal,
)

from modern_gl.application.default_accounts import (
    COST_OF_GOODS,
    CUSTOMER,
    RETAINED_EARNINGS,
    SUPPLIER,
    default_account,
)
from modern_gl.application.inventory import (
    INCOMING_TYPES,
    Inventory,
)
from modern_gl.desktop.cell_editing import resolve_choice
from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    ESC1,
    ESC2,
    ESC3,
    ESC_KEYS,
    EXPENSE,
    EXPENSE_MONTH,
    ITEM,
    KIND,
    KIND_NAMES,
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
    SEVERAL_MONTHS,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    VAT_DOCUMENTS,
    WAREHOUSE,
    InventoryGridRow,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.dates import earlier_months, iso_date, month_code, month_name, parse_month
from modern_gl.i18n import tr
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


# the account a new line's offset starts with, by the document (debt 11: by type, not 60/62/46)
OFFSET_PURPOSE = {
    "opening": SUPPLIER,
    "receipt": SUPPLIER,
    "sale": CUSTOMER,
    "purchase_return": SUPPLIER,
    "sale_return": CUSTOMER,
}
# the documents with a supplier or customer
PARTY_DOCUMENTS = {"receipt", "sale", "purchase_return", "sale_return"}
RETURNS = {"purchase_return", "sale_return"}


class InventoryLinesBase(QAbstractTableModel):
    changed = Signal()
    # «Товар» chosen in «Вид» of a service line: the page makes it an item (row)
    goods_wanted = Signal(int)

    def __init__(
        self,
        session: Session,
        doc_type: str,
        rows: list[InventoryGridRow] | None = None,
        read_only: bool = False,
        vat_rate: int | None = None,
        incoming_account: int | None = None,
        doc_date: date | str | None = None,
    ) -> None:
        super().__init__()
        self.incoming_account = incoming_account  # a mədaxil's: its reason's account (D91)
        self.s = session
        self.doc_type = doc_type
        # the document's date: the months before it are the ones an expense may belong to
        self.doc_date = iso_date(doc_date or session.working_date)
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
        # a purchase's supplier, a sale's customer, chosen in the header for every line;
        # `by_lines` — the lines have their own and show them
        self.party_account: int | None = None
        self.party_subconto: list[int | None] = [None, None, None]
        self.by_lines = False
        self.rows = rows or [self.default_row()]
        self._take_party()
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
        elif doc_type in RETURNS:  # goods only, at the price of the return
            self.columns = [
                ITEM, WAREHOUSE, QUANTITY, UNIT, PRICE, AMOUNT, VAT, ACCOUNT, SC1, SC2, SC3, MEMO
            ]  # fmt: skip
        else:
            self.columns = [
                ITEM,
                *([KIND] if doc_type == "receipt" else []),
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
                # last: rarely filled, so Enter after the expense's subconto skips past it
                *([EXPENSE_MONTH] if doc_type == "receipt" else []),
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
        if key == KIND:
            return [(kind, tr(name)) for kind, name in KIND_NAMES.items()]
        if key == ACCOUNT:
            return [(account.id, account.label) for account in self.s.catalog.leaf_accounts]
        if key == EXPENSE:  # goods come to a stock account through the warehouse only
            catalog = self.s.catalog
            return [
                (account.id, account.label)
                for account in catalog.leaf_accounts
                if not catalog.is_stock_account(account.id)
            ]
        if key == EXPENSE_MONTH:
            return [*self.month_choices(), (SEVERAL_MONTHS, tr("несколько месяцев…"))]
        kind_id = self.kind_at(row_index, key)
        owner = self.owner_at(row_index, key)
        return (
            [(value.id, value.label) for value in self.s.catalog.values(kind_id, owner)]
            if kind_id
            else []
        )

    def month_choices(self) -> list[tuple[int, str]]:
        """The twelve months before the document's, latest first (D65): an expense of the
        document's own month is accrued nowhere, so the cell is simply left empty."""
        return [(month_code(last), month_name(last[:7])) for last in earlier_months(self.doc_date)]

    def set_doc_date(self, doc_date: date | str) -> None:
        self.doc_date = iso_date(doc_date)

    def month_code_of(self, text: str) -> int:
        """The month a typed text names: by numbers ('09.2026') or by the list's names;
        SEVERAL_MONTHS when the range choice is picked."""
        typed = parse_month(text)
        if typed is not None:
            return month_code(typed)
        found = resolve_choice(self.choices(0, EXPENSE_MONTH), text)
        if found is None:
            raise ValueError(tr("месяц не распознан: {text}", text=text))
        return found

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

    def has_party(self) -> bool:
        """A purchase or a sale names its supplier or customer once, in the header."""
        return self.doc_type in PARTY_DOCUMENTS

    def _take_party(self) -> None:
        """The header's party from the lines: the one they share; none — the default
        account; lines with different ones show their own (`by_lines`)."""
        if not self.has_party():
            return
        offsets = {
            (row.offset_account_id, tuple(row.offset_subconto))
            for row in self.rows
            if not row.is_empty()
        }
        if len(offsets) > 1:  # the header still offers one for every line
            self.by_lines = True
            self.party_account = self.default_row().offset_account_id
            return
        account, subconto = offsets.pop() if offsets else (self.default_row().offset_account_id, ())
        self.party_account = account
        self.party_subconto = list(subconto) or [None, None, None]

    def party_in_header(self) -> bool:
        """Every line has the header's party: its account and subconto are not shown."""
        if not self.has_party() or self.by_lines or self.party_account is None:
            return False
        party = (self.party_account, self.party_subconto)
        return all(
            (row.offset_account_id, row.offset_subconto) == party
            for row in self.rows
            if not row.is_empty()
        )

    def set_party(self, account_id: int | None, subconto: list[int | None]) -> None:
        """The header's supplier or customer for every line: the lines that had the old
        one (or none) — and all of them when they had their own."""
        old = (self.party_account, self.party_subconto)
        for row in self.rows:
            same = (row.offset_account_id, row.offset_subconto) == old
            if self.by_lines or same or row.is_empty() or not any(row.offset_subconto):
                row.offset_account_id = account_id
                row.offset_subconto = list(subconto)
        self.party_account, self.party_subconto = account_id, list(subconto)
        self.by_lines = False
        self.beginResetModel()
        self.endResetModel()
        self.changed.emit()

    def default_row(self) -> InventoryGridRow:
        if self.has_party() and self.party_account is not None:  # the header's party
            return InventoryGridRow(
                offset_account_id=self.party_account, offset_subconto=list(self.party_subconto)
            )
        if self.doc_type == "incoming":
            return InventoryGridRow(offset_account_id=self.incoming_account)
        if self.doc_type in {"transfer", "landed_cost"}:
            return InventoryGridRow()
        purposes = [OFFSET_PURPOSE.get(self.doc_type, COST_OF_GOODS)]
        if self.doc_type == "opening" and self.stock_only:
            purposes.insert(0, RETAINED_EARNINGS)  # unseen (D90): not a supplier
        led, cid = self.s.ledger, self.s.company_id
        account = next(filter(None, (default_account(led, cid, p) for p in purposes)), None)
        # Subconto (counterparty, contract) stay empty: a guessed value would post silently.
        return InventoryGridRow(offset_account_id=account)

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
        if key == KIND:  # a line begun: an empty one becomes goods by its item
            return not self.rows[row].is_empty()
        if key in {WAREHOUSE, UNIT} and self.is_service(row):
            return False
        if key in ESC_KEYS | {EXPENSE, EXPENSE_MONTH} and not self.is_service(row):
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
        if key in {PRICE, AMOUNT} and self.doc_type not in {*INCOMING_TYPES, "sale", *RETURNS}:
            return False
        if key == VAT and self.doc_type not in VAT_DOCUMENTS:
            return False
        if key == CURRENCY_AMOUNT:  # in a currency the manat amount follows from the rate
            return self.rate is not None
        if key == EXPENSE_MONTH:
            return self.doc_type == "receipt"
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
