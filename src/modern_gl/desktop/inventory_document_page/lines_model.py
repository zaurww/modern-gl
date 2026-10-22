"""The lines of a warehouse document as a table model: what each cell shows and takes,
and the lines as the inputs of `Inventory`."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor

from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    Inventory,
    IssueLine,
    ReceiptLine,
    SaleLine,
    TransferLine,
    format_quantity,
    to_quantity,
    vat_of,
)
from modern_gl.application.queries import remembered_sale_subconto
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
    HEADERS,
    ITEM,
    LIST_KEYS,
    MEMO,
    NUMBER_KEYS,
    PASTE_ORDER,
    PRICE,
    QUANTITY,
    RECEIPT_HEADERS,
    SALE1,
    SALE2,
    SALE3,
    SALE_HEADERS,
    SALE_KEYS,
    SC1,
    SC2,
    SC3,
    SC_KEYS,
    STORED_FIELDS,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    VAT_DOCUMENTS,
    WAREHOUSE,
    InventoryGridRow,
    InventoryPaste,
    UnknownName,
    paste_columns,
)
from modern_gl.desktop.postings import (
    plain_number,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    money,
)
from modern_gl.domain.currency import to_base
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, round_ratio, to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    Choice,
    ItemChoice,
    item_choices,
    warehouse_choices,
)


class InventoryLinesModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        session: Session,
        doc_type: str,
        rows: list[InventoryGridRow] | None = None,
        read_only: bool = False,
        vat_rate: int | None = None,
    ) -> None:
        super().__init__()
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
        self.rows = rows or [self.default_row()]
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
        code = {"opening": "60", "receipt": "60", "sale": "62"}.get(self.doc_type, "46")
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
        if account is None or self.doc_type in {"transfer", "landed_cost"}:
            return InventoryGridRow()
        # Subconto (counterparty, contract) stay empty: a guessed value would post silently.
        return InventoryGridRow(offset_account_id=account.id)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                key = self.columns[section]
                if key == CURRENCY_AMOUNT and self.currency_code:
                    return tr("Сумма, {code}", code=self.currency_code)
                if key == AMOUNT and self.rate is not None:
                    return tr("Сумма, ₼")
                if self.doc_type == "sale" and key in SALE_HEADERS:
                    return tr(SALE_HEADERS[key])
                if self.doc_type == "receipt" and key in RECEIPT_HEADERS:
                    return tr(RECEIPT_HEADERS[key])
                if key in SALE_KEYS:
                    kind_id = self.sale_kind(key)
                    return self.s.catalog.kinds[kind_id] if kind_id else ""
                if key in SUBCONTO_KEYS and key[-1] != "1":
                    return self._kind_header(key)
                return tr(HEADERS[key])
            return str(section + 1)
        if (
            role == Qt.ItemDataRole.ToolTipRole
            and orientation == Qt.Orientation.Horizontal
            and self.columns[section] == ACCOUNT
        ):
            if self.doc_type == "sale":
                return tr("Счёт расчётов с покупателем")
            return tr("Счёт расчётов / затрат")
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            numbers = self.columns[section] in NUMBER_KEYS  # like their cells
            return (
                Qt.AlignmentFlag.AlignRight if numbers else Qt.AlignmentFlag.AlignLeft
            ) | Qt.AlignmentFlag.AlignVCenter
        return None

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

    def _kind_header(self, key: str) -> str:
        """A second or third subconto column is named by its directory («Anbar»,
        «Müqavilə»), when its lines agree on one; else it stays unnamed."""
        kinds = {
            self.kind_at(row, key)
            for row in range(len(self.rows))
            if self.applies(row, key) and not self.rows[row].is_empty()
        }
        if len(kinds) != 1:
            return ""
        (kind_id,) = kinds
        return self.s.catalog.kinds[kind_id] if kind_id is not None else ""

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
        if key in {PRICE, AMOUNT} and self.doc_type not in {"opening", "receipt", "sale"}:
            return False
        if key == VAT and self.doc_type not in VAT_DOCUMENTS:
            return False
        if key == CURRENCY_AMOUNT:  # in a currency the manat amount follows from the rate
            return self.rate is not None
        if key == AMOUNT and self.rate is not None:
            return False
        return self.doc_type != "landed_cost"

    def flags(self, index):
        key = self.key(index)
        if not self.applies(index.row(), key):
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.read_only and self.editable(key):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def _price(self, row: InventoryGridRow) -> int | None:
        """The price of a unit, in the document's currency."""
        value = row.currency_amount if self.rate is not None else row.amount
        if not row.quantity or value is None:
            return None
        return round_ratio(value * QUANTITY_FACTOR, row.quantity)

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        row = self.rows[index.row()]
        key = self.key(index)
        if role == Qt.ItemDataRole.EditRole:
            return self._edit_value(index.row(), key)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_text(index.row(), key)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in NUMBER_KEYS:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and (
            (key in SUBCONTO_KEYS and self._subconto_of(row, key)[int(key[-1]) - 1] is None)
            or (key == ITEM and self.is_service(index.row()) and not row.memo.strip())
        ):
            return QColor(P.tertiary)
        return None

    def _edit_value(self, row_index: int, key: str):
        """What an editor starts with: ids for list cells, plain numbers for amounts."""
        row = self.rows[row_index]
        if key == ITEM:
            return row.item_id
        if key in {WAREHOUSE, TO_WAREHOUSE}:
            return row.warehouse_id if key == WAREHOUSE else row.to_warehouse_id
        if key in {ACCOUNT, EXPENSE}:
            return self._account_of(row, key)
        if key in SUBCONTO_KEYS:
            return self._subconto_of(row, key)[int(key[-1]) - 1]
        if key == QUANTITY:
            return "" if row.quantity is None else format_quantity(row.quantity, 6)
        if key in {PRICE, AMOUNT, VAT, CURRENCY_AMOUNT}:
            value = {
                PRICE: self._price(row),
                AMOUNT: row.amount,
                VAT: row.vat_amount,
                CURRENCY_AMOUNT: row.currency_amount,
            }[key]
            return "" if value is None else format_minor(value).replace(" ", "")
        if key == UNIT:
            return self._display_text(row_index, key)
        return row.memo

    def _display_text(self, row_index: int, key: str) -> str:
        row = self.rows[row_index]
        item = self.items.get(row.item_id) if row.item_id is not None else None
        if key == ITEM:
            return self._item_text(row_index, item)
        if key in {WAREHOUSE, TO_WAREHOUSE}:
            warehouse_id = row.warehouse_id if key == WAREHOUSE else row.to_warehouse_id
            warehouse = self.warehouses.get(warehouse_id) if warehouse_id is not None else None
            return warehouse.label if warehouse else ""
        if key == QUANTITY:
            if row.quantity is None:
                return ""
            return format_quantity(row.quantity, item.precision if item else 6)
        if key == UNIT:
            return item.unit if item else ""
        if key in {PRICE, AMOUNT}:
            value = self._price(row) if key == PRICE else row.amount
            return "" if value is None else money(value)
        if key == VAT:
            return "" if row.vat_amount is None else money(row.vat_amount, blank_zero=False)
        if key == CURRENCY_AMOUNT:
            return money(row.currency_amount)
        if key in {ACCOUNT, EXPENSE}:
            account_id = self._account_of(row, key)
            account = self.s.catalog.accounts.get(account_id) if account_id is not None else None
            return account.label if account else ""
        if key in SUBCONTO_KEYS:
            value_id = self._subconto_of(row, key)[int(key[-1]) - 1]
            if value_id is not None:
                return self.s.catalog.value(value_id).name
            kind_id = self.kind_at(row_index, key)
            return self.s.catalog.kinds[kind_id] if kind_id else ""
        return row.memo

    def _item_text(self, row_index: int, item: ItemChoice | None) -> str:
        """An item's name; a sale's service shows what it is (its memo)."""
        row = self.rows[row_index]
        if item is None and self.is_service(row_index):
            return row.memo.strip() or tr("Услуга")
        return item.label if item else ""

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        row = self.rows[index.row()]
        key = self.key(index)
        if key == PRICE:
            if not row.quantity:
                raise ValidationError(tr("сначала укажите количество"))
            total = round_ratio(value * row.quantity, QUANTITY_FACTOR)
            if self.rate is not None:
                self._set_currency_amount(row, total)
            else:
                row.amount = total
            self._recalculate_vat(row)
        elif key == CURRENCY_AMOUNT:
            self._set_currency_amount(row, value)
        elif key == AMOUNT:
            row.amount = value
            self._recalculate_vat(row)
        elif key == VAT:
            row.vat_typed = value is not None  # cleared: calculated from the rate again
            row.vat_amount = value
            self._recalculate_vat(row)
        elif key == ACCOUNT:
            self._set_account(row, value)
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        elif key == EXPENSE:
            row.expense_account_id = value
            self._drop_foreign(value, row.expense_subconto)
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        elif key in SUBCONTO_KEYS:
            self._subconto_of(row, key)[int(key[-1]) - 1] = value
        else:
            self._set_stored(index.row(), key, value)
        self.dataChanged.emit(
            self.index(index.row(), 0), self.index(index.row(), len(self.columns) - 1)
        )
        self.changed.emit()
        return True

    def _set_stored(self, row_index: int, key: str, value) -> None:
        row = self.rows[row_index]
        setattr(row, STORED_FIELDS[key], value)
        if key == ITEM and value is None:
            row.warehouse_id = None  # a sale's service comes from no warehouse
        if key in {ITEM, MEMO}:
            self._remember_sale_subconto(row_index)

    def _remember_sale_subconto(self, row_index: int) -> None:
        """Empty sale subconto of a line take what the item (the service) had the last
        time it was sold — to this customer if it was — else what the line above has."""
        row = self.rows[row_index]
        if not self.sale_kinds or None not in row.sale_subconto[: len(self.sale_kinds)]:
            return
        catalog = self.s.catalog
        customer = next(
            (
                value
                for value in row.offset_subconto
                if value is not None and catalog.has_tax_id(catalog.value(value).kind_id)
            ),
            None,
        )
        remembered = (
            remembered_sale_subconto(
                self.s.conn, self.s.company_id, row.item_id, row.memo, customer
            )
            if row.item_id is not None or row.memo.strip()
            else ()
        )
        above = self.rows[row_index - 1].sale_subconto if row_index > 0 else []
        for value in (*remembered, *above):
            if value is None:
                continue
            kind = catalog.value(value).kind_id
            if kind in self.sale_kinds:
                position = self.sale_kinds.index(kind)
                if row.sale_subconto[position] is None:
                    row.sale_subconto[position] = value

    def _set_currency_amount(self, row: InventoryGridRow, value: int | None) -> None:
        row.currency_amount = value
        row.amount = None if value is None or self.rate is None else to_base(value, self.rate)

    def set_currency(self, code: str, rate: Fraction | None, in_currency: bool) -> None:
        """Amounts in a currency (`in_currency`) at `rate`, or in manat."""
        self.currency_code = code if in_currency else ""
        self.rate = rate if in_currency else None
        self.has_currency = in_currency
        for row in self.rows:
            if in_currency:
                row.amount = (
                    None
                    if row.currency_amount is None or rate is None
                    else to_base(row.currency_amount, rate)
                )
            else:
                row.currency_amount = None
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )
        self.changed.emit()

    def currency_total(self) -> int:
        return sum(row.currency_amount or 0 for row in self.rows)

    def _recalculate_vat(self, row: InventoryGridRow) -> None:
        """VAT follows the amount and the rate until it is typed by hand."""
        if self.doc_type not in VAT_DOCUMENTS or row.vat_typed:
            return
        row.vat_amount = (
            None
            if row.amount is None or self.vat_rate is None
            else vat_of(row.amount, self.vat_rate)
        )

    def set_vat_rate(self, rate: int | None) -> None:
        self.vat_rate = rate
        for row in self.rows:
            self._recalculate_vat(row)
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )
        self.changed.emit()

    def has_vat(self) -> bool:
        return self.vat_rate is not None or any(row.vat_amount for row in self.rows)

    def _set_account(self, row: InventoryGridRow, account_id: int | None) -> None:
        """Set the offset account and drop subconto values it no longer accepts."""
        row.offset_account_id = account_id
        self._drop_foreign(account_id, row.offset_subconto)

    def _drop_foreign(self, account_id: int | None, subconto: list[int | None]) -> None:
        """Drop the subconto values the account does not accept."""
        kinds = self.s.catalog.accounts[account_id].sc_kinds if account_id else (None, None, None)
        for position, kind in enumerate(kinds):
            current = subconto[position]
            if current is not None and (
                kind is None or self.s.catalog.value(current).kind_id != kind
            ):
                subconto[position] = None

    # ---- Excel ---------------------------------------------------------------------

    def parse(self, row_index: int, key: str, text: str):
        """The value of a cell from pasted text. Raises UnknownName for a new name."""
        text = text.strip()
        if key in {ITEM, WAREHOUSE, TO_WAREHOUSE}:
            value = resolve_choice(self.choices(row_index, key), text)
            if value is None:
                raise UnknownName(key, text)
            return value
        if key in {ACCOUNT, EXPENSE}:
            return self.s.catalog.resolve_account(text).id
        if key in SUBCONTO_KEYS:
            kind_id = self.kind_at(row_index, key)
            if kind_id is None:
                raise ValueError(tr("у счёта нет этого субконто: {text}", text=text))
            value = self.s.catalog.resolve_value(kind_id, text, self.owner_at(row_index, key))
            if value is None:
                raise UnknownName(key, text, kind_id)
            return value
        if key == QUANTITY:
            value = to_quantity(plain_number(text))
        elif key in {PRICE, AMOUNT, VAT, CURRENCY_AMOUNT}:
            value = to_minor(plain_number(text))
            if key == VAT and value == 0:
                return 0
        else:
            return text
        if value <= 0:
            raise ValueError(tr("должно быть больше нуля: {text}", text=text))
        return value

    def paste(self, text: str, start_row: int, start_column: int, shown) -> InventoryPaste:
        """Lines copied from Excel become lines of the document: by the header line if
        there is one (Товар, Количество, Цена, Сумма… in any order), else in the order
        of the table from the current column. `shown(column)` tells if it is visible.
        One line goes into the current row; more fill it if empty, then new rows."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        cells = [line.split("\t") for line in lines]
        result = InventoryPaste()
        if not cells or self.read_only:
            return result
        mapping = paste_columns(cells[0], self.columns)
        if mapping is not None:
            cells = cells[1:]
        target = start_row
        for n, line in enumerate(cells, start=1):
            if not any(cell.strip() for cell in line):
                continue
            needs_row = target >= len(self.rows) or not self.rows[target].is_empty()
            if (len(cells) > 1 or target >= len(self.rows)) and needs_row:
                self.insert_row(target)
            keys = mapping or self._columns_in_order(target, start_column, shown)
            pasted = {
                key: cell.strip()
                for key, cell in zip(keys, line, strict=False)
                if key is not None and cell.strip()
            }
            extra = [cell.strip() for cell in line[len(keys) :] if cell.strip()]
            if extra:
                result.errors.append(tr("строка {n}: лишнее значение «{text}»", n=n, text=extra[0]))
            self._paste_line(target, pasted, n, result)
            result.rows += 1
            target += 1
        self.changed.emit()
        return result

    def _columns_in_order(self, row_index: int, start: int, shown) -> list[str]:
        """Without a header the cells follow the visible columns of the table
        (subconto only as far as the line's account has them)."""
        return [
            key
            for column, key in enumerate(self.columns)
            if column >= start
            and shown(column)
            and (self.editable(key) or key == UNIT)
            and self.applies(row_index, key)
        ]

    def _paste_line(self, row_index: int, pasted: dict[str, str], n: int, result) -> None:
        for key in PASTE_ORDER:
            if key not in pasted or not self.editable(key):
                continue
            if key == PRICE and AMOUNT in pasted:
                continue  # the amount is exact; a price is rounded
            try:
                value = self.parse(row_index, key, pasted[key])
                self.setData(self.index(row_index, self.columns.index(key)), value)
            except UnknownName as e:
                result.unknown.append((row_index, key, e.text, e.kind_id))
                if key == ITEM and UNIT in pasted:
                    result.units[e.text] = pasted[UNIT]
            except (LookupError, ValueError, TypeError, LedgerError) as e:
                result.errors.append(tr("строка {n}: {error}", n=n, error=str(e).strip("'\"")))
        if MEMO in pasted and self.editable(MEMO):
            self.setData(self.index(row_index, self.columns.index(MEMO)), pasted[MEMO])
        row = self.rows[row_index]
        if row.warehouse_id is None and len(self.warehouses) == 1:  # the only one there is
            row.warehouse_id = next(iter(self.warehouses))

    def copy_text(self, shown) -> str:
        """The lines as tab-separated text with a header, for Excel."""
        columns = [c for c in range(len(self.columns)) if shown(c)]

        def title(key: str) -> str:
            if key in SALE_KEYS:
                return str(self.headerData(self.columns.index(key), Qt.Orientation.Horizontal))
            if key in SUBCONTO_KEYS:
                caption = "Субконто" if key in SC_KEYS else "Субконто затрат"
                return f"{tr(caption)} {key[-1]}"
            return tr(HEADERS[key])

        lines = ["\t".join(title(self.columns[c]) for c in columns)]
        for r, row in enumerate(self.rows):
            if row.is_empty():
                continue
            values = []
            for c in columns:
                key = self.columns[c]
                if key in LIST_KEYS:
                    filled = self._edit_value(r, key) is not None
                    values.append(self._display_text(r, key) if filled else "")
                else:
                    values.append(str(self._edit_value(r, key) or ""))
            lines.append("\t".join(values))
        return "\n".join(lines) + "\n"

    def insert_row(self, at: int | None = None, row: InventoryGridRow | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row or self.default_row())
        self.endInsertRows()
        self.changed.emit()
        return at

    def duplicate_row(self, index: int) -> int:
        return self.insert_row(index + 1, self.rows[index].copy())

    def remove_row(self, index: int) -> None:
        self.beginRemoveRows(QModelIndex(), index, index)
        del self.rows[index]
        self.endRemoveRows()
        if not self.rows:
            self.insert_row()
        self.changed.emit()

    def total(self) -> int:
        return sum(row.amount or 0 for row in self.rows)

    def vat_total(self) -> int:
        return sum(row.vat_amount or 0 for row in self.rows)

    def to_inputs(
        self, complete: bool = True
    ) -> list[ReceiptLine] | list[IssueLine] | list[TransferLine] | list[SaleLine]:
        """Lines for saving. A draft (complete=False) needs only the item of each line."""
        rows = [row for row in self.rows if not row.is_empty()]
        if not rows:
            raise ValidationError(tr("складской документ без строк"))
        result = []
        for line_no, row in enumerate(rows, 1):
            item_id = row.item_id
            if item_id is None and self.doc_type not in {"sale", "receipt"}:  # a service
                raise ValidationError(tr("строка {line}: не указан товар", line=line_no))
            if complete:
                self._validate_complete(row, line_no)
            quantity = None if row.quantity is None else Decimal(row.quantity).scaleb(-6)
            if self.doc_type == "sale":
                result.append(
                    SaleLine(
                        item_id,
                        row.warehouse_id,
                        quantity,
                        None if row.amount is None else Decimal(row.amount).scaleb(-MONEY_SCALE),
                        None
                        if row.vat_amount is None
                        else Decimal(row.vat_amount).scaleb(-MONEY_SCALE),
                        row.memo.strip(),
                        row.offset_account_id,
                        tuple(row.offset_subconto),
                        row.line_id,
                        tuple(
                            row.sale_subconto[position]
                            for position, key in enumerate((SALE1, SALE2, SALE3))
                            if self._takes_sale(row, key)
                        ),
                    )
                )
                continue
            if self.doc_type in {"opening", "receipt"}:
                result.append(
                    ReceiptLine(
                        item_id,
                        row.warehouse_id,
                        quantity,
                        None if row.amount is None else Decimal(row.amount).scaleb(-MONEY_SCALE),
                        row.memo.strip(),
                        row.offset_account_id,
                        tuple(row.offset_subconto),
                        row.line_id,
                        None
                        if row.vat_amount is None
                        else Decimal(row.vat_amount).scaleb(-MONEY_SCALE),
                        None
                        if row.currency_amount is None
                        else Decimal(row.currency_amount).scaleb(-MONEY_SCALE),
                        row.expense_account_id if item_id is None else None,
                        tuple(row.expense_subconto) if item_id is None else (),
                    )
                )
                continue
            assert item_id is not None  # only a sale's or receipt's line may have none
            if self.doc_type == "issue":
                result.append(
                    IssueLine(
                        item_id,
                        row.warehouse_id,
                        quantity,
                        row.offset_account_id,
                        tuple(row.offset_subconto),
                        row.memo.strip(),
                        row.line_id,
                    )
                )
            elif self.doc_type == "transfer":
                result.append(
                    TransferLine(
                        item_id,
                        row.warehouse_id,
                        row.to_warehouse_id,
                        quantity,
                        row.memo.strip(),
                        row.line_id,
                    )
                )
        return result

    def _validate_complete(self, row: InventoryGridRow, line_no: int) -> None:
        self._validate_what(row, line_no)
        if self.doc_type == "transfer":
            if row.to_warehouse_id is None:
                raise ValidationError(tr("строка {line}: не указан склад-получатель", line=line_no))
            return
        if self.doc_type in {"opening", "receipt", "sale"} and (
            row.amount is None or row.amount <= 0
        ):
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if self.rate is not None and not row.currency_amount:
            raise ValidationError(tr("строка {line}: не указана сумма в валюте", line=line_no))
        if row.offset_account_id is None:
            raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
        self._require_subconto(row.offset_account_id, row.offset_subconto, line_no)
        for key in (SALE1, SALE2, SALE3):  # a sales group: what the sale accounts ask for
            kind_id = self.sale_kind(key)
            if kind_id is None or not self._takes_sale(row, key):
                continue
            if (
                kind_id not in self.s.catalog.owner_kinds
                and row.sale_subconto[int(key[-1]) - 1] is None
            ):
                raise ValidationError(
                    tr(
                        "строка {line}: заполните субконто «{kind}»",
                        line=line_no,
                        kind=self.s.catalog.kinds[kind_id],
                    )
                )

    def _validate_what(self, row: InventoryGridRow, line_no: int) -> None:
        """What the line is: an item from a warehouse, or a sale's service, or a receipt's
        service or fixed asset with the account it goes to."""
        if self.doc_type == "sale" and row.item_id is None:  # a service: no stock
            if not row.memo.strip():
                raise ValidationError(
                    tr("строка {line}: укажите товар или что за услуга", line=line_no)
                )
        elif self.doc_type == "receipt" and row.item_id is None:  # a service, a fixed asset
            if not row.memo.strip():
                raise ValidationError(
                    tr("строка {line}: укажите товар или что куплено (услуга, ОС)", line=line_no)
                )
            if row.expense_account_id is None:
                raise ValidationError(tr("строка {line}: не указан счёт затрат", line=line_no))
            if self.s.catalog.is_stock_account(row.expense_account_id):
                account = self.s.catalog.accounts[row.expense_account_id]
                raise ValidationError(
                    tr(
                        "строка {line}: счёт {account} складской — выберите товар в колонке "
                        "«Товар», тогда он придёт на склад",
                        line=line_no,
                        account=account.short,
                    )
                )
            self._require_subconto(row.expense_account_id, row.expense_subconto, line_no)
        else:
            if row.warehouse_id is None:
                raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
            if row.quantity is None or row.quantity <= 0:
                raise ValidationError(tr("строка {line}: не указано количество", line=line_no))

    def _require_subconto(self, account_id: int, subconto: list[int | None], line_no: int) -> None:
        """Every subconto of the account but a contract: many suppliers have none, only the
        e-qaimə; reports show such amounts as «not given»."""
        catalog = self.s.catalog
        account = catalog.accounts[account_id]
        for position, kind_id in enumerate(account.sc_kinds):
            # a contract belongs to a counterparty; a kind added to an account with postings
            optional = kind_id in catalog.owner_kinds or position in account.sc_optional
            if kind_id is not None and subconto[position] is None and not optional:
                raise ValidationError(
                    tr(
                        "строка {line}: заполните субконто «{kind}»",
                        line=line_no,
                        kind=self.s.catalog.kinds[kind_id],
                    )
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
