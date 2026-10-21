"""Editable multi-line warehouse document and its posted document card."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    STANDARD_VAT_RATE,
    Inventory,
    InventoryDocumentData,
    IssueLine,
    ReceiptLine,
    SaleLine,
    TransferLine,
    format_quantity,
    to_quantity,
    vat_of,
)
from modern_gl.application.queries import remembered_sale_subconto
from modern_gl.desktop.inventory_page import ItemDialog
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.postings import (
    TABS,
    CellEditor,
    attach_account_list,
    attach_list,
    edit_again,
    edit_current,
    edit_next,
    holds_on_group,
    plain_number,
    tabbed_in,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    CutCellTips,
    button,
    date_edit,
    edited_date,
    enter_goes_on,
    money,
    to_qdate,
)
from modern_gl.domain.accounts import INPUT_VAT, OUTPUT_VAT
from modern_gl.domain.currency import format_unit_rate, parse_rate, to_base, unit_rate
from modern_gl.domain.dates import earlier_months, month_name
from modern_gl.domain.eqaime import status_group, status_label
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.invoice import CUSTOMS, EQAIME
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, round_ratio, to_minor
from modern_gl.i18n import fold, tr
from modern_gl.i18n_az import AZ
from modern_gl.reporting.eqaime_reconciliation import portal_status
from modern_gl.reporting.inventory import (
    Choice,
    ItemChoice,
    item_choices,
    stock_account_choices,
    unit_choices,
    warehouse_choices,
)

ITEM = "item"
WAREHOUSE = "warehouse"
TO_WAREHOUSE = "to_warehouse"
QUANTITY = "quantity"
UNIT = "unit"
PRICE = "price"
AMOUNT = "amount"
CURRENCY_AMOUNT = "currency_amount"
VAT = "vat"
ACCOUNT = "account"
SC1 = "sc1"
SC2 = "sc2"
SC3 = "sc3"
# a receipt's line without an item (a service, a fixed asset): the account it goes to
EXPENSE = "expense"
ESC1 = "esc1"
ESC2 = "esc2"
ESC3 = "esc3"
# a sale line: the subconto of the sale's own accounts (46; 90.1 / 90.2 / 90.3) that
# the customer, the item and the warehouse do not give — a sales group, a channel (D61)
SALE1 = "sale1"
SALE2 = "sale2"
SALE3 = "sale3"
MEMO = "memo"
SC_KEYS = {SC1, SC2, SC3}  # the subconto of the line's offset (supplier, customer) account
ESC_KEYS = {ESC1, ESC2, ESC3}
SALE_KEYS = {SALE1, SALE2, SALE3}
SUBCONTO_KEYS = SC_KEYS | ESC_KEYS | SALE_KEYS
# cells that store the edited value as is
STORED_FIELDS = {
    ITEM: "item_id",
    WAREHOUSE: "warehouse_id",
    TO_WAREHOUSE: "to_warehouse_id",
    QUANTITY: "quantity",
    AMOUNT: "amount",
    MEMO: "memo",
}
LIST_KEYS = {ITEM, WAREHOUSE, TO_WAREHOUSE, ACCOUNT, EXPENSE} | SUBCONTO_KEYS
# the name of a line keeps this much; these columns narrow first, down to NARROW_MIN
ITEM_MIN = 300
NARROW_MIN = 84
SOFT_KEYS = {WAREHOUSE, TO_WAREHOUSE, ACCOUNT, EXPENSE} | SUBCONTO_KEYS
NUMBER_KEYS = {QUANTITY, PRICE, AMOUNT, CURRENCY_AMOUNT, VAT}
# the VAT of a receipt or a sale: rate in hundredths of a percent, None = without VAT
VAT_RATES = [(STANDARD_VAT_RATE, "18%"), (None, "Без НДС")]
VAT_DOCUMENTS = {"receipt", "sale"}

HEADERS = {
    ITEM: "Товар",
    WAREHOUSE: "Склад",
    TO_WAREHOUSE: "Склад-получатель",
    QUANTITY: "Количество",
    UNIT: "Ед.",
    PRICE: "Цена",
    AMOUNT: "Сумма",
    CURRENCY_AMOUNT: "В валюте",
    VAT: "НДС",
    ACCOUNT: "Корр. счёт",  # the header stays short; its tooltip says more
    SC1: "Субконто",
    SC2: "",
    SC3: "",
    EXPENSE: "Счёт затрат",
    ESC1: "Субконто затрат",
    ESC2: "",
    ESC3: "",
    SALE1: "",  # the name of the directory
    SALE2: "",
    SALE3: "",
    MEMO: "Комментарий",
}
# a sale line is goods or a service: a line without an item, its memo says what it is
SALE_HEADERS = {ITEM: "Товар / услуга", MEMO: "Содержание"}
# a receipt line without an item: a service, a fixed asset or any expense bought
RECEIPT_HEADERS = {ITEM: "Товар / услуга / ОС", MEMO: "Содержание"}

DOCUMENT_TYPES = {
    "opening": "Начальные остатки",
    "receipt": "Покупка",
    "issue": "Списание",
    "sale": "Продажа",
    "transfer": "Перемещение",
    "landed_cost": "Дополнительные расходы",
}

HINT = (
    "Enter, Tab — дальше   ·   Shift+Tab — назад   ·   Ins — строка   ·   F9 — копия строки   ·   "
    "Del — удалить строку   ·   Ctrl+V — вставить из Excel   ·   Ctrl+S — сохранить   ·   "
    "Ctrl+Enter — провести"
)


def _names(*sources: str) -> set[str]:
    """A header in Russian and in Azerbaijani, folded for matching."""
    return {fold(name) for src in sources for name in (src, AZ.get(src, src))}


# Excel header -> column; "Субконто" columns go in a row after the account
PASTE_HEADERS = [
    (_names("Товар", "Наименование", "Номенклатура", "Mal", "Malın adı", "Ad"), ITEM),
    (_names("Склад", "Anbar"), WAREHOUSE),
    (_names("Склад-получатель"), TO_WAREHOUSE),
    (_names("Количество", "Кол-во", "Miqdar"), QUANTITY),
    (_names("Ед.", "Ед", "Единица", "Единица измерения", "Vahid", "Ölçü vahidi"), UNIT),
    (_names("Цена", "Qiymət"), PRICE),
    (_names("Сумма", "Məbləğ", "Сумма без НДС", "ƏDV-siz məbləğ"), AMOUNT),
    (_names("НДС", "Сумма НДС", "ƏDV", "ƏDV məbləği"), VAT),
    (_names("Корр. счёт", "Счёт", "Hesab"), ACCOUNT),
    (_names("Комментарий", "Содержание", "Şərh", "Məzmun"), MEMO),
]
SUBCONTO_HEADERS = _names("Субконто", "Subkonto")
# accounts before their subconto, the quantity before a price, a pasted amount over a price
PASTE_ORDER = [
    ITEM,
    WAREHOUSE,
    TO_WAREHOUSE,
    QUANTITY,
    ACCOUNT,
    SC1,
    SC2,
    SC3,
    PRICE,
    CURRENCY_AMOUNT,
    AMOUNT,
    VAT,
]


class UnknownName(LookupError):
    """A pasted name that is not in its list yet: an item, a warehouse or a subconto."""

    def __init__(self, key: str, text: str, kind_id: int | None = None) -> None:
        super().__init__(text)
        self.key, self.text, self.kind_id = key, text, kind_id


@dataclass
class InventoryPaste:
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    # row, column key, name, subconto kind (None for an item or a warehouse)
    unknown: list[tuple[int, str, str, int | None]] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)  # a new item -> its pasted unit


def paste_columns(cells: list[str], columns: list[str]) -> list[str | None] | None:
    """The columns of a header line, or None if the line is not a header."""
    result: list[str | None] = []
    position = 0
    for cell in cells:
        words = fold(cell.strip()).split()
        name = " ".join(words)
        key = next((k for names, k in PASTE_HEADERS if name in names), None)
        if key is None and words and words[0] in SUBCONTO_HEADERS:
            digits = [int(w) for w in words if w.isdigit()]
            position = digits[0] if digits else position + 1
            key = f"sc{position}" if 1 <= position <= 3 else None
        result.append(key if key in columns else None)
    return result if sum(k is not None for k in result) >= 2 else None


@dataclass
class InventoryGridRow:
    item_id: int | None = None
    warehouse_id: int | None = None
    to_warehouse_id: int | None = None
    quantity: int | None = None
    amount: int | None = None
    offset_account_id: int | None = None
    offset_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    memo: str = ""
    line_id: int | None = None  # the stored line; landed cost refers to it
    vat_amount: int | None = None
    vat_typed: bool = False  # typed by hand: a new amount or rate no longer recalculates it
    currency_amount: int | None = None  # a receipt in a currency
    # a receipt's line without an item: the account and subconto its value goes to
    expense_account_id: int | None = None
    expense_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    # a sale's line: a value for each of the model's `sale_kinds`
    sale_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])

    def is_empty(self) -> bool:
        """Nothing typed yet: the account and subconto prefilled by default do not count."""
        return (
            self.item_id is None
            and self.warehouse_id is None
            and self.to_warehouse_id is None
            and self.quantity is None
            and self.amount is None
            and not self.memo.strip()
        )

    def copy(self) -> InventoryGridRow:
        return InventoryGridRow(
            self.item_id,
            self.warehouse_id,
            self.to_warehouse_id,
            self.quantity,
            self.amount,
            self.offset_account_id,
            list(self.offset_subconto),
            self.memo,
            vat_amount=self.vat_amount,
            vat_typed=self.vat_typed,
            currency_amount=self.currency_amount,
            expense_account_id=self.expense_account_id,
            expense_subconto=list(self.expense_subconto),
            sale_subconto=list(self.sale_subconto),
        )  # a copy is a new line: no line id


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
            value = _resolve_choice(self.choices(row_index, key), text)
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


def _resolve_choice(choices: list[tuple[int, str]], text: str) -> int | None:
    """Exact label, name or code, else a unique fragment; None if nothing matches."""
    needle = fold(text)
    exact = [
        choice_id
        for choice_id, label in choices
        if needle in {fold(label), fold(label.split("  ", 1)[-1]), fold(label.split("  ", 1)[0])}
    ]
    if exact:
        return exact[0]
    partial = [(choice_id, label) for choice_id, label in choices if needle in fold(label)]
    if len(partial) > 1:
        starts = [choice for choice in partial if fold(choice[1]).startswith(needle)]
        partial = starts if len(starts) == 1 else partial
    if len(partial) > 1:
        names = ", ".join(label for _, label in partial[:5])
        raise LookupError(tr("«{text}» подходит к нескольким: {names}", text=text, names=names))
    return partial[0][0] if partial else None


def _widen(editor: QLineEdit) -> None:
    """The editor of a name grows over the next cells to show it whole (up to the
    table's edge), and back to the cell as the text gets shorter."""
    cell = editor.property("cell_width") or editor.width()
    parent = editor.parentWidget()
    room = parent.width() - editor.x() if parent is not None else cell
    need = editor.fontMetrics().horizontalAdvance(editor.text()) + 24
    editor.resize(max(cell, min(need, room)), editor.height())
    editor.raise_()


UNSET = object()  # a cell edit that sets nothing


class InventoryLinesDelegate(QStyledItemDelegate):
    """Enter or Tab commits a cell; a name missing from a directory can be added on the spot."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text
    unknown_item = Signal(QPersistentModelIndex, str)
    # index, name, picked as "+ Добавить «…»" (then added without a question)
    unknown_warehouse = Signal(QPersistentModelIndex, str, bool)
    # (kind_id, name, owner_id) -> the new element's id: a subconto list offers
    # "+ Добавить «…»" (see `attach_list`)
    add_value: Callable[[int, str, int | None], int] | None = None

    def createEditor(self, parent, option, index):
        model: InventoryLinesModel = index.model()
        key = model.key(index)
        editor = CellEditor(parent)
        editor.setFrame(False)
        if key in LIST_KEYS:
            # Directory cells open with the whole list; the account list starts with typing.
            labels = [label for _, label in model.choices(index.row(), key)]
            if key in {ACCOUNT, EXPENSE}:
                attach_account_list(editor, labels, model.s.catalog, self._chosen)
            else:
                # a new item or warehouse, like a new contract, is offered in the list
                can_add = key in (ITEM, WAREHOUSE) or (
                    key in SUBCONTO_KEYS and self.add_value is not None
                )
                attach_list(editor, labels, True, self._chosen, can_add=can_add)
        elif key in NUMBER_KEYS:
            editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if key == ITEM:  # a long name of an e-qaimə line is seen whole while edited
            editor.textChanged.connect(lambda _text, widget=editor: _widen(widget))
        editor.returnPressed.connect(lambda widget=editor: self._commit_and_next(widget))
        return editor

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, option, index)
        if index.model().key(index) == ITEM:
            editor.setProperty("cell_width", editor.width())
            _widen(editor)

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        model: InventoryLinesModel = index.model()
        value = index.data(Qt.ItemDataRole.EditRole)
        if model.key(index) == ITEM and model.is_service(index.row()):
            value = model.rows[index.row()].memo  # what the service is, to read or correct
        elif model.key(index) in LIST_KEYS:
            value = "" if value is None else index.data(Qt.ItemDataRole.DisplayRole)
        editor.setText(value or "")
        editor.selectAll()

    def _subconto_value(self, editor, model, index, key: str, text: str) -> object:
        """The element named; one its directory lacks is added when picked as
        "+ Добавить «…»", else the page is told. UNSET: nothing to set."""
        kind_id = model.kind_at(index.row(), key)
        if kind_id is None:  # the account has no subconto at this position
            return UNSET
        owner = model.owner_at(index.row(), key)
        value = model.s.catalog.resolve_value(kind_id, text, owner) if text else None
        if not text or value is not None:
            return value
        if editor.property("gl_add") and self.add_value is not None:
            return self.add_value(kind_id, text, owner)
        editor.setProperty("gl_unknown", True)  # the cursor waits in the cell for the answer
        self.unknown_value.emit(QPersistentModelIndex(index), kind_id, text)
        return UNSET

    def setModelData(self, editor, model, index):
        model = cast(InventoryLinesModel, model)
        key = model.key(index)
        text = editor.text().strip()
        try:
            if key in {ACCOUNT, EXPENSE}:
                value = model.s.catalog.resolve_account(text).id if text else None
            elif key in SUBCONTO_KEYS:
                value = self._subconto_value(editor, model, index, key, text)
                if value is UNSET:  # no subconto here, or the page asks about the name
                    return
            elif key in LIST_KEYS:
                value = _resolve_choice(model.choices(index.row(), key), text) if text else None
                if key == ITEM and text and value is None and model.is_service(index.row()):
                    # the service's name corrected: it stays a service
                    model.setData(model.index(index.row(), model.columns.index(MEMO)), text)
                    return
                if text and value is None:
                    editor.setProperty("gl_unknown", True)  # the cell waits for the answer
                    where = QPersistentModelIndex(index)
                    if key == ITEM:
                        self.unknown_item.emit(where, text)
                    else:
                        self.unknown_warehouse.emit(where, text, bool(editor.property("gl_add")))
                    return
            elif key == QUANTITY:
                value = to_quantity(text) if text else None
            elif key in {PRICE, AMOUNT, VAT, CURRENCY_AMOUNT}:
                value = to_minor(text) if text else None
                if value is not None and (value < 0 or (value == 0 and key != VAT)):  # VAT 0 ok
                    raise ValueError(tr("сумма должна быть больше нуля"))
            else:
                value = text
            model.setData(index, value)
        except (LedgerError, LookupError, ValueError, TypeError) as exc:
            self.error.emit(str(exc).strip("'\""))

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
        ):
            self._commit_and_next(editor)  # Tab as Enter: a group holds the cell
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backtab:
            self._commit_and_next(editor, QAbstractItemDelegate.EndEditHint.EditPreviousItem)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor, hint=QAbstractItemDelegate.EndEditHint.EditNextItem) -> None:
        """Enter and Tab alike; a group, or a name its directory lacks, keeps the cell."""
        if editor.property("inventory_done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("inventory_done", True)
        self.commitData.emit(editor)
        if editor.property("gl_unknown"):
            hint = QAbstractItemDelegate.EndEditHint.NoHint
        self.closeEditor.emit(editor, hint)


class InventoryLinesTable(QTableView):
    def __init__(self, model: InventoryLinesModel, delegate: InventoryLinesDelegate) -> None:
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.setShowGrid(False)
        self.setWordWrap(False)
        CutCellTips(self)
        self.setTabKeyNavigation(True)
        self.verticalHeader().setDefaultSectionSize(34)
        self.configure_columns()

    def configure_columns(self) -> None:
        model = self.model()
        # Fits an ordinary window without a horizontal scroll bar: the item name takes
        # what is left; subconto positions no account uses are not shown.
        widths = {
            WAREHOUSE: 110,
            TO_WAREHOUSE: 110,
            QUANTITY: 100,
            UNIT: 64,
            PRICE: 84,
            AMOUNT: 96,
            CURRENCY_AMOUNT: 104,
            VAT: 84,
            ACCOUNT: 130,
            EXPENSE: 130,
            **dict.fromkeys(SALE_KEYS, 130),  # named after its directory: «Satış qrupları»
        }
        used = model.s.catalog.used_positions()
        expenses = model.has_expenses()
        goods = model.has_goods()
        expense_positions = model.expense_positions()
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        self._widths = {
            key: widths.get(key, 100 if key in SUBCONTO_KEYS else 120) for key in model.columns
        }
        for column, key in enumerate(model.columns):
            self.setColumnWidth(column, self._widths[key])
            self.setColumnHidden(column, False)  # a column of the previous model may be hidden
            if key in SC_KEYS:
                self.setColumnHidden(column, int(key[-1]) not in used)
            if key in {WAREHOUSE, UNIT}:
                self.setColumnHidden(column, not goods)
            if key == EXPENSE:
                self.setColumnHidden(column, not expenses)
            if key in ESC_KEYS:
                self.setColumnHidden(column, not expenses or int(key[-1]) not in expense_positions)
            if key in SALE_KEYS:
                self.setColumnHidden(
                    column, not any(model.applies(r, key) for r in range(model.rowCount()))
                )
            if key == VAT:
                self.setColumnHidden(column, not model.has_vat())
            if key == CURRENCY_AMOUNT:
                self.setColumnHidden(column, not model.has_currency)
            if key == ITEM:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self._fit_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """The name keeps ITEM_MIN px: in a narrow window the account, subconto and
        warehouse columns give up width first (their text gets «…»), down to NARROW_MIN."""
        model = self.model()
        widths = getattr(self, "_widths", None)
        if not widths:
            return
        shown = [
            (column, key)
            for column, key in enumerate(model.columns)
            if key != ITEM and not self.isColumnHidden(column)
        ]
        soft = [(column, key) for column, key in shown if key in SOFT_KEYS]
        fixed = sum(widths[key] for _, key in shown if key not in SOFT_KEYS)
        room = self.viewport().width() - fixed - ITEM_MIN
        wanted = sum(widths[key] for _, key in soft)
        scale = 1.0 if wanted <= 0 or room >= wanted else max(room, 0) / wanted
        for column, key in soft:
            self.setColumnWidth(column, max(NARROW_MIN, int(widths[key] * scale)))

    def model(self) -> InventoryLinesModel:
        return cast(InventoryLinesModel, super().model())

    def closeEditor(self, editor, hint):
        index = self.currentIndex()
        model = self.model()
        if not index.isValid():
            super().closeEditor(editor, hint)
            return
        editable = [
            column
            for column, key in enumerate(model.columns)
            if not self.isColumnHidden(column)
            and model.editable(key)
            and model.applies(index.row(), key)
        ]
        if (
            hint == QAbstractItemDelegate.EndEditHint.EditNextItem
            and index.isValid()
            and not model.read_only
            and index.row() == model.rowCount() - 1
            and editable
            and index.column() == editable[-1]
        ):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            row = model.insert_row()
            new_index = model.index(row, 0)
            self.setCurrentIndex(new_index)
            self.edit(new_index)
            return
        super().closeEditor(editor, hint)

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            index = self.currentIndex()
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEditable:
                self.edit(index)
                return
        super().keyPressEvent(event)
        if event.key() in TABS:  # Tab moves on as Enter does: into the next cell, open
            edit_current(self)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if tabbed_in(event):
            edit_current(self)


class NewNamesDialog(QDialog):
    """Names pasted from Excel that are not in the lists yet: add them all at once.
    New items need a unit (pick one or type a new one) and a stock account."""

    def __init__(self, session: Session, listing: str, items: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Новые элементы справочников"))
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        text = QLabel(tr("Этих элементов нет в справочниках. Добавить?\n\n{names}", names=listing))
        text.setWordWrap(True)
        form.addRow(text)
        self.unit = QComboBox()
        self.unit.setEditable(True)
        for unit in unit_choices(session.conn, session.company_id):
            self.unit.addItem(unit.label, unit.id)
        if not self.unit.count():
            self.unit.setEditText(tr("шт"))
        self.account = QComboBox()
        for account in stock_account_choices(session.conn, session.company_id):
            self.account.addItem(account.label, account.id)
        if items:
            form.addRow(tr("Единица новых товаров"), self.unit)
            form.addRow(tr("Счёт запасов"), self.account)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class InventoryDocumentPage(QWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)

    def __init__(
        self,
        session: Session,
        document_id: int | None = None,
        doc_type: str = "receipt",
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.doc: InventoryDocumentData | None = None
        self.doc_type = doc_type
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)

        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        self.memo.setPlaceholderText(tr("Комментарий складского документа"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        meta = QHBoxLayout()
        date_caption = QLabel(tr("Дата"))
        date_caption.setObjectName("secondary")
        meta.addWidget(date_caption)
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addSpacing(12)
        type_caption = QLabel(tr("Операция"))
        type_caption.setObjectName("secondary")
        meta.addWidget(type_caption)
        self.type_label = QLabel(tr(DOCUMENT_TYPES.get(doc_type, doc_type)))
        self.type_label.setFont(fonts().heading)
        meta.addWidget(self.type_label)
        meta.addSpacing(12)
        self.vat_caption = QLabel(tr("НДС"))
        self.vat_caption.setObjectName("secondary")
        meta.addWidget(self.vat_caption)
        self.vat_rate = PickBox()
        self.vat_rate.setFixedWidth(110)
        for rate, label in VAT_RATES:
            self.vat_rate.addItem(tr(label), rate)
        meta.addWidget(self.vat_rate)
        meta.addSpacing(12)
        # the basis of a receipt: an e-qaimə, or a customs declaration for imported goods
        self.basis = PickBox()
        self.basis.setFixedWidth(120)
        self.basis.addItem(tr("E-qaimə"), EQAIME)
        self.basis.addItem(tr("Декларация"), CUSTOMS)
        self.basis.setCurrentIndex(0)
        self.basis.setToolTip(tr("Основание: e-qaimə или таможенная декларация (импорт)"))
        meta.addWidget(self.basis)
        self.invoice_caption = QLabel(tr("E-qaimə"))  # a sale's basis is always an e-qaimə
        self.invoice_caption.setObjectName("secondary")
        meta.addWidget(self.invoice_caption)
        self.invoice = QLineEdit()
        self.invoice.setFixedWidth(170)
        self.invoice.setPlaceholderText(tr("номер"))
        meta.addWidget(self.invoice)
        # what the portal said of it when last read: awaiting approval, cancelled… (D53)
        self.portal_status = Chip()
        self.portal_status.hide()
        meta.addWidget(self.portal_status)
        meta.addSpacing(12)
        # services of an earlier month whose e-qaimə came later: accrued there (D63)
        self.expense_caption = QLabel(tr("Расход за"))
        self.expense_caption.setObjectName("secondary")
        meta.addWidget(self.expense_caption)
        self.expense_month = PickBox()
        self.expense_month.setFixedWidth(150)
        self.expense_month.setToolTip(
            tr(
                "Месяц расхода по услугам, если e-qaimə пришла позже: расход начисляется "
                "последним днём этого месяца (Дт затрат / Кт 76H), долг поставщику и НДС — "
                "датой e-qaimə"
            )
        )
        meta.addWidget(self.expense_month)
        meta.addSpacing(12)
        self.currency_caption = QLabel(tr("Валюта"))
        self.currency_caption.setObjectName("secondary")
        meta.addWidget(self.currency_caption)
        self.currency = PickBox()
        self.currency.setFixedWidth(80)
        self.currency.addItem("AZN", None)
        for currency in session.catalog.active_currencies:
            self.currency.addItem(currency.code, currency.id)
        self.currency.setCurrentIndex(0)
        meta.addWidget(self.currency)
        self.rate_caption = QLabel(tr("Курс"))
        self.rate_caption.setObjectName("secondary")
        meta.addWidget(self.rate_caption)
        self.rate = QLineEdit()
        self.rate.setFixedWidth(90)
        self.rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.rate.setPlaceholderText(tr("курс"))
        self.rate.setToolTip(tr("Курс на дату документа; можно исправить (например, курс таможни)"))
        meta.addWidget(self.rate)
        self.rate_typed = False  # typed by hand: a new date no longer changes it
        meta.addStretch(1)
        root.addLayout(meta)

        # a new receipt (sale) has VAT when the company has an account to post its VAT to
        vat_role = OUTPUT_VAT if doc_type == "sale" else INPUT_VAT
        has_vat_account = session.ledger.account_role(session.company_id, vat_role) is not None
        self._show_vat_rate(STANDARD_VAT_RATE if has_vat_account else None)
        self.model = InventoryLinesModel(session, doc_type, vat_rate=self._chosen_vat_rate())
        self.delegate = InventoryLinesDelegate(self)
        self.table = InventoryLinesTable(self.model, self.delegate)
        self.expense_columns = self._expense_columns()  # shown for these
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        summary = QHBoxLayout()
        self.hint = QLabel(tr(HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        summary.addWidget(self.hint, 1)
        summary.addSpacing(24)
        self.currency_total = QLabel()
        self.currency_total.setObjectName("secondary")
        summary.addWidget(self.currency_total)
        summary.addSpacing(16)
        self.vat_total_caption = QLabel(tr("НДС"))
        self.vat_total_caption.setObjectName("secondary")
        summary.addWidget(self.vat_total_caption)
        self.vat_total = QLabel()
        self.vat_total.setMinimumWidth(90)
        self.vat_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.vat_total)
        summary.addSpacing(16)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
        summary.addWidget(total_caption)
        self.total = QLabel()
        self.total.setMinimumWidth(130)
        self.total.setFont(fonts().total)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.total)
        root.addLayout(summary)

        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_accrual = button(tr("Начисление"), "flat")
        self.btn_accrual.setToolTip(tr("Проводки начисления расхода в месяце услуги"))
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_accrual)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        self.btn_accrual.clicked.connect(self._open_accrual)
        self._connect_delegate()
        self.model.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.vat_rate.activated.connect(self._vat_rate_changed)
        self.basis.activated.connect(self._changed)
        self.invoice.textEdited.connect(self._changed)
        self.expense_month.activated.connect(self._changed)
        self.currency.activated.connect(self._currency_changed)
        self.rate.textEdited.connect(self._rate_edited)
        self.date.dateChanged.connect(self._date_changed)
        self.date.dateChanged.connect(self._expense_months_changed)
        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self._grid_shortcut("Ins", self._insert_row, while_editing=True)
        self._grid_shortcut("F9", self._duplicate_row, while_editing=True)
        self._grid_shortcut("Del", self._remove_row)
        self._grid_shortcut("Ctrl+V", self.paste)  # inside a cell editor: its own paste
        self._grid_shortcut("Ctrl+C", self.copy)

        if document_id is None:
            self._set_new()
        else:
            self.load(document_id)

    @property
    def document_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("inventory_doc", self.document_id) if self.doc else ("new_inventory", id(self))

    def title(self) -> str:
        operation = tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type))
        title = (
            f"{operation} №{self.doc.number}" if self.doc else tr("Новое: {type}", type=operation)
        )
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.table.setFocus()

    def keyPressEvent(self, event) -> None:
        """Enter in the comment, date, VAT, basis, currency or rate goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _shortcut(self, keys: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.activated.connect(callback)

    def _grid_shortcut(self, keys: str, callback, *, while_editing: bool = False) -> None:
        shortcut = QShortcut(QKeySequence(keys), self.table)
        shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
            if while_editing
            else Qt.ShortcutContext.WidgetShortcut
        )
        shortcut.activated.connect(callback)

    def _insert_row(self) -> None:
        if self.model.read_only:
            return
        self._finish_editing()
        current = self.table.currentIndex()
        at = current.row() + 1 if current.isValid() else None
        row = self.model.insert_row(at)
        self.table.setCurrentIndex(self.model.index(row, 0))

    def _duplicate_row(self) -> None:
        self._finish_editing()
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        row = self.model.duplicate_row(current.row())
        self.table.setCurrentIndex(self.model.index(row, 0))

    def _remove_row(self) -> None:
        self._finish_editing()
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self.model.remove_row(current.row())

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    # ---- clipboard -----------------------------------------------------------------

    def _shown(self, column: int) -> bool:
        return not self.table.isColumnHidden(column)

    def paste(self, text: str | None = None) -> None:
        """Lines copied from Excel become lines of the document."""
        if self.model.read_only or self.doc_type == "landed_cost":
            return
        text = QApplication.clipboard().text() if text is None else text
        if not text.strip():
            return
        self.error.hide()
        current = self.table.currentIndex()
        row, column = (current.row(), current.column()) if current.isValid() else (0, 0)
        result = self.model.paste(text, row, column, self._shown)
        problems = list(result.errors)
        if result.unknown:
            try:
                added = self._add_unknown(result)
            except (LedgerError, LookupError) as exc:
                added, problems = False, [*problems, str(exc)]
            if not added:
                problems += [
                    tr("нет в справочнике: {text}", text=text) for _, _, text, _ in result.unknown
                ]
        if problems:
            more = len(problems) - 6
            self.show_error(
                "\n".join(problems[:6]) + (f"\n{tr('и ещё {n}', n=more)}" if more > 0 else "")
            )
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def _add_unknown(self, result: InventoryPaste) -> bool:
        """Add the new items, warehouses and subconto in one go and put them in place."""
        names: dict[tuple[str, int | None, str], None] = {}
        for _, key, text, kind_id in result.unknown:
            group = ITEM if key == ITEM else WAREHOUSE if kind_id is None else "sc"
            names[(group, kind_id, text)] = None
        titles = {ITEM: tr("Товар"), WAREHOUSE: tr("Склад")}
        listing = "\n".join(
            f"{titles[group] if kind_id is None else self.s.catalog.kinds[kind_id]}: {text}"
            for group, kind_id, text in list(names)[:12]
        )
        items = any(group == ITEM for group, _, _ in names)
        dialog = NewNamesDialog(self.s, listing, items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if items and dialog.account.currentData() is None:
            raise LookupError(tr("В плане счетов нет счёта с субконто Товар и Склад"))
        units: dict[str, int] = {}
        created: dict[tuple, int] = {}
        cid = self.s.company_id
        for row, key, text, kind_id in result.unknown:
            if key == ITEM:
                if (ITEM, text) not in created:
                    unit = self._unit(result.units.get(text) or dialog.unit.currentText(), units)
                    account = int(dialog.account.currentData())
                    created[(ITEM, text)] = self.inventory.add_item(cid, text, unit, account)
                value = created[(ITEM, text)]
            elif kind_id is None:  # a warehouse
                if (WAREHOUSE, text) not in created:
                    created[(WAREHOUSE, text)] = self.inventory.add_warehouse(cid, text)
                value = created[(WAREHOUSE, text)]
            else:  # a contract belongs to the counterparty its line has by then
                owner = self.model.owner_at(row, key)
                if (kind_id, text, owner) not in created:
                    value_id = self.s.ledger.add_subconto_value(cid, kind_id, text, owner_id=owner)
                    self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner)
                    created[(kind_id, text, owner)] = value_id
                value = created[(kind_id, text, owner)]
            self.s.catalog.reload()
            self.model.refresh_choices()
            self.model.setData(self.model.index(row, self.model.columns.index(key)), value)
        return True

    def _unit(self, text: str, made: dict[str, int]) -> int:
        """A unit by its code or name; a new one if there is none."""
        text = text.strip()
        choices = [(c.id, c.label) for c in unit_choices(self.s.conn, self.s.company_id)]
        try:
            found = _resolve_choice(choices, text) if text else None
        except LookupError:
            found = None
        if found is None:
            if not text:
                raise LookupError(tr("Заполните название и единицу"))
            if fold(text) not in made:
                made[fold(text)] = self.inventory.add_unit(self.s.company_id, text, text)
            found = made[fold(text)]
        return found

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Строки скопированы — их можно вставить в Excel"))

    def _connect_delegate(self) -> None:
        self.delegate.error.connect(self.show_error)
        self.delegate.add_value = self._add_typed_value
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        self.delegate.unknown_value.connect(
            lambda index, kind_id, text: QTimer.singleShot(
                0, lambda: self._create_value(index, kind_id, text)
            )
        )
        self.delegate.unknown_item.connect(
            lambda index, text: QTimer.singleShot(0, lambda: self._create_item(index, text))
        )
        self.delegate.unknown_warehouse.connect(
            lambda index, text, picked: QTimer.singleShot(
                0, lambda: self._create_warehouse(index, text, ask=not picked)
            )
        )

    def _ask_add(self, text: str, directory: str) -> bool:
        answer = QMessageBox.question(
            self,
            tr("Новый элемент справочника"),
            tr("«{text}» нет в справочнике «{kind}». Добавить?", text=text, kind=directory),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        kind = self.s.catalog.kinds[kind_id]
        if not index.isValid():
            return
        if not self._ask_add(text, kind):
            edit_again(self.table, index, text)  # the name, to correct it
            return
        owner = self.model.owner_at(index.row(), self.model.columns[index.column()])
        value_id = self._add_typed_value(kind_id, text, owner)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        edit_next(self.table, index)

    def _add_typed_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        kind = self.s.catalog.kinds[kind_id]
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
        return value_id

    def _create_item(self, index: QPersistentModelIndex, text: str) -> None:
        if not index.isValid():
            return
        if self.doc_type in {"sale", "receipt"}:
            answer = self._service_or_item(text)
            if answer is None:
                edit_again(self.table, index, text)  # the name, to correct it
                return
            if answer == "service":  # what was typed says what the service is
                self._make_service(index.row(), text)
                return
        dialog = ItemDialog(self.s, self.inventory, self, name=text)
        if dialog.units.count() == 0:
            self.show_error(tr("Сначала добавьте единицу измерения"))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.item_id is None:
            edit_again(self.table, index, text)
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), dialog.item_id)
        self.s.notify(tr("Товар добавлен"))
        edit_next(self.table, index)

    def _make_service(self, row: int, text: str) -> None:
        """The line becomes a service with this text; a receipt's goes on to the account the
        service (fixed asset) is charged to."""
        self.model.setData(self.model.index(row, self.model.columns.index(MEMO)), text)
        self.model.setData(self.model.index(row, self.model.columns.index(ITEM)), None)
        self.table.configure_columns()
        key = EXPENSE if self.doc_type == "receipt" else QUANTITY
        index = self.model.index(row, self.model.columns.index(key))
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def _service_or_item(self, text: str) -> str | None:
        """A name the item list does not have: a service (fixed asset), or a new item?"""
        sale = self.doc_type == "sale"
        box = QMessageBox(self)
        box.setWindowTitle(tr(DOCUMENT_TYPES[self.doc_type]))
        box.setText(
            tr("«{text}» нет среди товаров. Это услуга или новый товар?", text=text)
            if sale
            else tr("«{text}» нет среди товаров. Это услуга, ОС или новый товар?", text=text)
        )
        service = box.addButton(
            tr("Услуга") if sale else tr("Услуга, ОС"), QMessageBox.ButtonRole.AcceptRole
        )
        item = box.addButton(tr("Новый товар…"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(service)
        box.exec()
        clicked = box.clickedButton()
        return "service" if clicked is service else "item" if clicked is item else None

    def _create_warehouse(self, index: QPersistentModelIndex, text: str, ask: bool = True) -> None:
        """A warehouse the list lacks; picked as "+ Добавить «…»" it goes in at once."""
        if not index.isValid():
            return
        if ask and not self._ask_add(text, tr("Склад")):
            edit_again(self.table, index, text)
            return
        try:
            warehouse_id = self.inventory.add_warehouse(self.s.company_id, text)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), warehouse_id)
        self.s.notify(tr("Склад «{name}» добавлен", name=text))
        edit_next(self.table, index)

    def _show_vat_rate(self, rate: int | None) -> None:
        index = self.vat_rate.findData(rate)
        if index < 0:  # a rate not in the list (set elsewhere): show it as it is
            self.vat_rate.addItem(f"{Decimal(rate or 0).scaleb(-2).normalize():f}%", rate)
            index = self.vat_rate.count() - 1
        self.vat_rate.setCurrentIndex(index)
        with_vat = self.doc_type in VAT_DOCUMENTS
        self.vat_caption.setVisible(with_vat)
        self.vat_rate.setVisible(with_vat)

    def _chosen_vat_rate(self) -> int | None:
        return self.vat_rate.currentData() if self.doc_type in VAT_DOCUMENTS else None

    def _vat_rate_changed(self, *_args) -> None:
        self.model.set_vat_rate(self._chosen_vat_rate())
        self.table.configure_columns()

    # ---- currency -------------------------------------------------------------------

    def _chosen_currency(self) -> int | None:
        return self.currency.currentData() if self.doc_type == "receipt" else None

    def _typed_rate(self) -> Fraction | None:
        try:
            return unit_rate(parse_rate(plain_number(self.rate.text())))
        except (TypeError, ValueError):
            return None

    def _rate_of_the_day(self) -> None:
        """The rate in force on the document's date (unless the rate was typed)."""
        currency_id = self._chosen_currency()
        if currency_id is None or self.rate_typed:
            return
        found = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        self.rate.setText(format_unit_rate(found.per_unit) if found else "")

    def _apply_currency(self) -> None:
        in_currency = self._chosen_currency() is not None
        for widget in (self.rate_caption, self.rate):
            widget.setVisible(in_currency)
        if in_currency:  # an import has no Azerbaijani VAT: it comes with customs
            self._show_vat_rate(None)
            self.model.set_vat_rate(None)
        self.vat_rate.setEnabled(not in_currency and not self.model.read_only)
        self.model.set_currency(self.currency.currentText(), self._typed_rate(), in_currency)
        self.table.configure_columns()

    def _currency_changed(self, *_args) -> None:
        self.rate_typed = False
        self._rate_of_the_day()
        self._apply_currency()

    def _rate_edited(self, *_args) -> None:
        self.rate_typed = True
        self._apply_currency()

    def _date_changed(self, *_args) -> None:
        if self._chosen_currency() is not None and not self.rate_typed:
            self._rate_of_the_day()
            self._apply_currency()

    def _show_totals(self) -> None:
        in_currency = self.model.rate is not None
        self.currency_total.setVisible(in_currency)
        self.currency_total.setText(
            f"{money(self.model.currency_total(), blank_zero=False)} {self.model.currency_code}"
        )
        vat = self.model.vat_total()
        shown = self.doc_type in VAT_DOCUMENTS and self.model.has_vat()
        self.vat_total_caption.setVisible(shown)
        self.vat_total.setVisible(shown)
        self.vat_total.setText(money(vat, blank_zero=False))
        self.total.setText(money(self.model.total() + vat, blank_zero=False))

    def _changed(self, *_args) -> None:
        self._show_totals()
        if self._expense_columns() != self.expense_columns:  # a service line came or went
            self.table.configure_columns()
            self.expense_columns = self._expense_columns()
            self._show_expense_month()
        if not self.model.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def _expense_columns(self) -> tuple[bool, set[int], bool]:
        return self.model.has_expenses(), self.model.expense_positions(), self.model.has_goods()

    def _set_new(self) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        self._apply_mode(False)
        self._show_currency(None, None)
        self._show_basis(EQAIME, "")
        self._fill_expense_months(None)
        self.dirty = False  # showing the defaults is not an edit
        self._show_totals()

    def _show_basis(self, kind: str, number: str) -> None:
        """The e-qaimə / declaration of a receipt, the e-qaimə of a sale; other documents
        have none."""
        self.basis.setCurrentIndex(max(self.basis.findData(kind), 0))
        self.invoice.setText(number)
        self.basis.setVisible(self.doc_type == "receipt")
        self.invoice_caption.setVisible(self.doc_type == "sale")
        self.invoice.setVisible(self.doc_type in VAT_DOCUMENTS)
        self._show_portal_status(kind, number)

    def _show_portal_status(self, kind: str, number: str) -> None:
        """Only what is worth a look: an approved e-qaimə shows nothing."""
        status = None
        if kind == EQAIME and self.doc_type in ("receipt", "sale"):
            status = portal_status(self.s.conn, self.s.company_id, self.doc_type == "sale", number)
        group = status_group(status or "")
        if status is None or group == "turnover":
            self.portal_status.hide()
            return
        self.portal_status.set(status_label(status), "red" if group == "void" else "neutral")
        self.portal_status.setToolTip(tr("Статус на портале при последней загрузке"))
        self.portal_status.show()

    def _invoice(self) -> dict[str, str]:
        """The basis for saving: number and kind (an empty number: none)."""
        number = self.invoice.text().strip()
        if self.doc_type == "sale":
            return {"invoice": number}
        return {"invoice": number, "invoice_kind": self.basis.currentData() if number else ""}

    # ---- the month of the expense (D63) --------------------------------------------

    def _fill_expense_months(self, chosen: str | None) -> None:
        """The months a receipt's services may belong to: the document's own (nothing is
        accrued) or one of the twelve before it, each as its last day."""
        self.expense_month.clear()
        self.expense_month.addItem(tr("месяц документа"), None)
        for last in earlier_months(edited_date(self.date)):
            self.expense_month.addItem(month_name(last[:7]), last)
        if chosen is not None and self.expense_month.findData(chosen) < 0:
            self.expense_month.addItem(month_name(chosen[:7]), chosen)  # saved earlier
        self.expense_month.setCurrentIndex(max(self.expense_month.findData(chosen), 0))
        self._show_expense_month()

    def _expense_months_changed(self, *_args) -> None:
        self._fill_expense_months(self._expense_date())

    def _expense_date(self) -> str | None:
        return self.expense_month.currentData() if self.doc_type == "receipt" else None

    def _show_expense_month(self) -> None:
        """Only a receipt with services (or with a month already chosen) asks for it."""
        shown = self.doc_type == "receipt" and (
            self.model.has_expenses() or self._expense_date() is not None
        )
        self.expense_caption.setVisible(shown)
        self.expense_month.setVisible(shown)

    def _show_currency(self, currency_id: int | None, rate: int | None) -> None:
        receipt = self.doc_type == "receipt"
        self.currency.setCurrentIndex(max(self.currency.findData(currency_id), 0))
        self.rate.setText("" if rate is None else format_unit_rate(unit_rate(rate)))
        self.rate_typed = rate is not None  # a saved rate stays as it was
        for widget in (self.currency_caption, self.currency):
            widget.setVisible(receipt)
        self._apply_currency()

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.doc_type = self.doc.doc_type
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.type_label.setText(tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type)))
        self._show_vat_rate(self.doc.vat_rate)
        vat_rate = self._chosen_vat_rate()
        kinds = sale_kinds(self.s) if self.doc_type == "sale" else []
        rows = [
            InventoryGridRow(
                line.item_id,
                line.warehouse_id,
                line.to_warehouse_id,
                line.quantity or None,
                line.amount or None,
                line.offset_account_id,
                list(line.offset_subconto),
                line.memo,
                line.id,
                vat_amount=line.vat_amount if vat_rate is not None or line.vat_amount else None,
                vat_typed=line.vat_amount != vat_of(line.amount, vat_rate),
                currency_amount=line.currency_amount,
                expense_account_id=line.cost_account_id if self.doc_type == "receipt" else None,
                expense_subconto=(
                    list(line.cost_subconto) if self.doc_type == "receipt" else [None, None, None]
                ),
                sale_subconto=by_sale_kinds(self.s.catalog, kinds, line.cost_subconto),
            )
            for line in self.doc.lines
        ] or [InventoryGridRow()]
        read_only = not self.doc.editable  # a posted document is edited in place, as in 1C
        self.model = InventoryLinesModel(
            self.s, self.doc_type, rows, read_only=read_only, vat_rate=vat_rate
        )
        self.table.setModel(self.model)
        self.table.configure_columns()
        self.expense_columns = self._expense_columns()
        self.delegate = InventoryLinesDelegate(self)
        self._connect_delegate()
        self.table.setItemDelegate(self.delegate)
        self.model.changed.connect(self._changed)
        if self.doc.status == "posted":
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self._apply_mode(read_only)
        self._show_currency(self.doc.currency_id, self.doc.currency_rate)
        self._show_basis(self.doc.invoice_kind, self.doc.invoice)
        self._fill_expense_months(self.doc.expense_date)
        self.dirty = False
        self._show_totals()
        self.title_changed.emit()

    def _apply_mode(self, read_only: bool) -> None:
        self.memo.setReadOnly(read_only)
        self.memo.setEnabled(not read_only)
        self.date.setEnabled(not read_only)
        self.vat_rate.setEnabled(not read_only)
        self.currency.setEnabled(not read_only)
        self.rate.setReadOnly(read_only)
        self.basis.setEnabled(not read_only)
        self.invoice.setReadOnly(read_only)
        self.expense_month.setEnabled(not read_only)
        self.model.read_only = read_only
        posted = self.doc is not None and self.doc.status == "posted"
        editable = not read_only and self.doc_type != "landed_cost"
        self.btn_save.setVisible(editable and not posted)  # Ctrl+S reposts a posted one
        self.btn_post.setVisible(editable)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(posted and self.doc_type != "landed_cost")
        self.btn_gl.setVisible(self.doc is not None and self.doc.gl_document_id is not None)
        self.btn_accrual.setVisible(
            self.doc is not None and self.doc.accrual_document_id is not None
        )
        self.hint.setVisible(not read_only and self.doc_type != "landed_cost")

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def save(self, post: bool) -> bool:
        if self.model.read_only or self.doc_type == "landed_cost":
            return False
        self._finish_editing()
        self.table.setFocus()
        self.error.hide()
        try:
            if self.doc is not None and self.doc.status == "posted":
                # edited in place: posted again at once, later documents recalculated
                post = True
                inputs = self.model.to_inputs(complete=True)
                with self.inventory.reposting(self.s.company_id, self.doc.id):
                    document_id = self._save_draft(inputs)
            else:
                inputs = self.model.to_inputs(complete=post)
                document_id = self._save_draft(inputs)
                if post:
                    self.inventory.post_document(self.s.company_id, document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return False
        self.s.working_date = edited_date(self.date)
        self.load(document_id)
        assert self.doc is not None  # load() has just read it
        self.s.notify(
            tr(
                "Складской документ №{n} проведён" if post else "Складской документ №{n} сохранён",
                n=self.doc.number,
            )
        )
        self.saved.emit(document_id)
        return True

    def _save_draft(self, inputs) -> int:
        company_id = self.s.company_id
        document_date = edited_date(self.date)
        memo = self.memo.text().strip()
        if self.doc_type in {"opening", "receipt"}:
            first = inputs[0]
            if self.doc is None:
                return self.inventory.create_receipt_draft(
                    company_id,
                    document_date,
                    inputs,
                    first.credit_account_id,
                    first.credit_subconto,
                    memo,
                    opening=self.doc_type == "opening",
                    vat_rate=self._chosen_vat_rate(),
                    currency_id=self._chosen_currency(),
                    currency_rate=self._rate_text(),
                    expense_date=self._expense_date(),
                    **self._invoice(),
                )
            self.inventory.update_receipt_draft(
                company_id,
                self.doc.id,
                document_date,
                inputs,
                first.credit_account_id,
                first.credit_subconto,
                memo,
                vat_rate=self._chosen_vat_rate(),
                currency_id=self._chosen_currency(),
                currency_rate=self._rate_text(),
                expense_date=self._expense_date(),
                **self._invoice(),
            )
            return self.doc.id
        if self.doc_type == "sale":
            first = inputs[0]
            header = (first.customer_account_id, first.customer_subconto, memo)
            extra = {"vat_rate": self._chosen_vat_rate(), **self._invoice()}
            if self.doc is None:
                return self.inventory.create_sale_draft(
                    company_id, document_date, inputs, *header, **extra
                )
            self.inventory.update_sale_draft(
                company_id, self.doc.id, document_date, inputs, *header, **extra
            )
            return self.doc.id
        if self.doc_type == "issue":
            if self.doc is None:
                return self.inventory.create_issue_draft(company_id, document_date, inputs, memo)
            self.inventory.update_issue_draft(company_id, self.doc.id, document_date, inputs, memo)
            return self.doc.id
        if self.doc is None:
            return self.inventory.create_transfer_draft(company_id, document_date, inputs, memo)
        self.inventory.update_transfer_draft(company_id, self.doc.id, document_date, inputs, memo)
        return self.doc.id

    def _rate_text(self) -> str | None:
        if self._chosen_currency() is None:
            return None
        return plain_number(self.rate.text()) or None

    def delete(self) -> None:
        if self.doc is None:
            return
        if (
            QMessageBox.question(
                self,
                tr("Удалить складской документ"),
                tr("Удалить складской документ №{n}?", n=self.doc.number),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        number = self.doc.number
        try:
            self.inventory.delete_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.dirty = False
        self.s.notify(tr("Складской документ №{n} удалён", n=number))
        self.saved.emit(self.doc.id)
        self.close_requested.emit()

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.inventory.unpost_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.load(self.doc.id)
        self.s.notify(
            tr(
                "Проведение складского документа №{n} отменено — можно исправлять",
                n=self.doc.number,
            )
        )
        self.saved.emit(self.doc.id)

    def _open_gl(self) -> None:
        if self.doc is not None and self.doc.gl_document_id is not None:
            self.open_gl_document.emit(self.doc.gl_document_id)

    def _open_accrual(self) -> None:
        if self.doc is not None and self.doc.accrual_document_id is not None:
            self.open_gl_document.emit(self.doc.accrual_document_id)
