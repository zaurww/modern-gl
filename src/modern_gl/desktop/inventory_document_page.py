"""Editable multi-line warehouse document and its posted document card."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import cast

from PySide6.QtCore import (
    QAbstractTableModel,
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
    TransferLine,
    format_quantity,
    to_quantity,
    vat_of,
)
from modern_gl.desktop.inventory_page import ItemDialog
from modern_gl.desktop.postings import attach_list, plain_number
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import Chip, button, date_edit, edited_date, money, to_qdate
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.currency import format_unit_rate, parse_rate, to_base, unit_rate
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, round_ratio, to_minor
from modern_gl.i18n import fold, tr
from modern_gl.i18n_az import AZ
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
MEMO = "memo"
# cells that store the edited value as is
STORED_FIELDS = {
    ITEM: "item_id",
    WAREHOUSE: "warehouse_id",
    TO_WAREHOUSE: "to_warehouse_id",
    QUANTITY: "quantity",
    AMOUNT: "amount",
    MEMO: "memo",
}
LIST_KEYS = {ITEM, WAREHOUSE, TO_WAREHOUSE, ACCOUNT, SC1, SC2, SC3}
NUMBER_KEYS = {QUANTITY, PRICE, AMOUNT, CURRENCY_AMOUNT, VAT}
# the VAT of a receipt: rate in hundredths of a percent, None = without VAT
VAT_RATES = [(STANDARD_VAT_RATE, "18%"), (None, "Без НДС")]

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
    MEMO: "Комментарий",
}

DOCUMENT_TYPES = {
    "opening": "Начальные остатки",
    "receipt": "Поступление",
    "issue": "Списание",
    "transfer": "Перемещение",
    "landed_cost": "Дополнительные расходы",
}

HINT = (
    "Enter / Tab — следующее поле   ·   Ins — строка   ·   F9 — копия строки   ·   "
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
        self.vat_rate = vat_rate if doc_type == "receipt" else None
        self.rate: Fraction | None = None  # a receipt in a currency: manat per unit
        self.currency_code = ""
        self.items = self._items()
        self.warehouses = self._warehouses()
        self.has_currency = False
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
                *([VAT] if doc_type == "receipt" else []),
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
        kind_id = self.kind_at(row_index, key)
        owner = self.owner_at(row_index, key)
        return (
            [(value.id, value.label) for value in self.s.catalog.values(kind_id, owner)]
            if kind_id
            else []
        )

    def owner_at(self, row_index: int, key: str) -> int | None:
        """The counterparty chosen on the line, for its contracts (None: any contract)."""
        row = self.rows[row_index]
        if key not in {SC1, SC2, SC3} or row.offset_account_id is None:
            return None
        account = self.s.catalog.accounts[row.offset_account_id]
        return self.s.catalog.owner_in(account, row.offset_subconto, int(key[-1]) - 1)

    def default_row(self) -> InventoryGridRow:
        code = "60" if self.doc_type in {"opening", "receipt"} else "46"
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
                return tr(HEADERS[key])
            return str(section + 1)
        if (
            role == Qt.ItemDataRole.ToolTipRole
            and orientation == Qt.Orientation.Horizontal
            and self.columns[section] == ACCOUNT
        ):
            return tr("Счёт расчётов / затрат")
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            numbers = self.columns[section] in NUMBER_KEYS  # like their cells
            return (
                Qt.AlignmentFlag.AlignRight if numbers else Qt.AlignmentFlag.AlignLeft
            ) | Qt.AlignmentFlag.AlignVCenter
        return None

    def key(self, index: QModelIndex) -> str:
        return self.columns[index.column()]

    def kind_at(self, row_index: int, key: str) -> int | None:
        if key not in {SC1, SC2, SC3}:
            return None
        account_id = self.rows[row_index].offset_account_id
        if account_id is None:
            return None
        return self.s.catalog.accounts[account_id].sc_kinds[int(key[-1]) - 1]

    def applies(self, row: int, key: str) -> bool:
        return key not in {SC1, SC2, SC3} or self.kind_at(row, key) is not None

    def editable(self, key: str) -> bool:
        if key in {UNIT}:
            return False
        if key in {PRICE, AMOUNT} and self.doc_type not in {"opening", "receipt"}:
            return False
        if key == VAT and self.doc_type != "receipt":
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
        if (
            role == Qt.ItemDataRole.ForegroundRole
            and key in {SC1, SC2, SC3}
            and row.offset_subconto[int(key[-1]) - 1] is None
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
        if key == ACCOUNT:
            return row.offset_account_id
        if key in {SC1, SC2, SC3}:
            return row.offset_subconto[int(key[-1]) - 1]
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
            return item.label if item else ""
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
        if key == ACCOUNT:
            account_id = row.offset_account_id
            account = self.s.catalog.accounts.get(account_id) if account_id is not None else None
            return account.label if account else ""
        if key in {SC1, SC2, SC3}:
            value_id = row.offset_subconto[int(key[-1]) - 1]
            if value_id is not None:
                return self.s.catalog.value(value_id).name
            kind_id = self.kind_at(row_index, key)
            return self.s.catalog.kinds[kind_id] if kind_id else ""
        return row.memo

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
        elif key in {SC1, SC2, SC3}:
            row.offset_subconto[int(key[-1]) - 1] = value
        else:
            setattr(row, STORED_FIELDS[key], value)
        self.dataChanged.emit(
            self.index(index.row(), 0), self.index(index.row(), len(self.columns) - 1)
        )
        self.changed.emit()
        return True

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
        if self.doc_type != "receipt" or row.vat_typed:
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
        kinds = self.s.catalog.accounts[account_id].sc_kinds if account_id else (None, None, None)
        for position, kind in enumerate(kinds):
            current = row.offset_subconto[position]
            if current is not None and (
                kind is None or self.s.catalog.value(current).kind_id != kind
            ):
                row.offset_subconto[position] = None

    # ---- Excel ---------------------------------------------------------------------

    def parse(self, row_index: int, key: str, text: str):
        """The value of a cell from pasted text. Raises UnknownName for a new name."""
        text = text.strip()
        if key in {ITEM, WAREHOUSE, TO_WAREHOUSE}:
            value = _resolve_choice(self.choices(row_index, key), text)
            if value is None:
                raise UnknownName(key, text)
            return value
        if key == ACCOUNT:
            return self.s.catalog.resolve_account(text).id
        if key in {SC1, SC2, SC3}:
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
            return f"{tr('Субконто')} {key[-1]}" if key in {SC1, SC2, SC3} else tr(HEADERS[key])

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
    ) -> list[ReceiptLine] | list[IssueLine] | list[TransferLine]:
        """Lines for saving. A draft (complete=False) needs only the item of each line."""
        rows = [row for row in self.rows if not row.is_empty()]
        if not rows:
            raise ValidationError(tr("складской документ без строк"))
        result = []
        for line_no, row in enumerate(rows, 1):
            if row.item_id is None:
                raise ValidationError(tr("строка {line}: не указан товар", line=line_no))
            if complete:
                self._validate_complete(row, line_no)
            quantity = None if row.quantity is None else Decimal(row.quantity).scaleb(-6)
            if self.doc_type in {"opening", "receipt"}:
                result.append(
                    ReceiptLine(
                        row.item_id,
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
                    )
                )
            elif self.doc_type == "issue":
                result.append(
                    IssueLine(
                        row.item_id,
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
                        row.item_id,
                        row.warehouse_id,
                        row.to_warehouse_id,
                        quantity,
                        row.memo.strip(),
                        row.line_id,
                    )
                )
        return result

    def _validate_complete(self, row: InventoryGridRow, line_no: int) -> None:
        if row.warehouse_id is None:
            raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
        if row.quantity is None or row.quantity <= 0:
            raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
        if self.doc_type == "transfer":
            if row.to_warehouse_id is None:
                raise ValidationError(tr("строка {line}: не указан склад-получатель", line=line_no))
            return
        if self.doc_type in {"opening", "receipt"} and (row.amount is None or row.amount <= 0):
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if self.rate is not None and not row.currency_amount:
            raise ValidationError(tr("строка {line}: не указана сумма в валюте", line=line_no))
        if row.offset_account_id is None:
            raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
        account = self.s.catalog.accounts[row.offset_account_id]
        for position, kind_id in enumerate(account.sc_kinds):
            if kind_id is not None and row.offset_subconto[position] is None:
                raise ValidationError(
                    tr(
                        "строка {line}: заполните субконто «{kind}»",
                        line=line_no,
                        kind=self.s.catalog.kinds[kind_id],
                    )
                )


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


class InventoryLinesDelegate(QStyledItemDelegate):
    """Enter or Tab commits a cell; a name missing from a directory can be added on the spot."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text
    unknown_item = Signal(QPersistentModelIndex, str)
    unknown_warehouse = Signal(QPersistentModelIndex, str)

    def createEditor(self, parent, option, index):
        model: InventoryLinesModel = index.model()
        key = model.key(index)
        editor = QLineEdit(parent)
        editor.setFrame(False)
        if key in LIST_KEYS:
            # Directory cells open with the whole list; the account list starts with typing.
            labels = [label for _, label in model.choices(index.row(), key)]
            attach_list(editor, labels, key != ACCOUNT, self._chosen)
        elif key in NUMBER_KEYS:
            editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        editor.returnPressed.connect(lambda widget=editor: self._commit_and_next(widget))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        model: InventoryLinesModel = index.model()
        value = index.data(Qt.ItemDataRole.EditRole)
        if model.key(index) in LIST_KEYS:
            value = "" if value is None else index.data(Qt.ItemDataRole.DisplayRole)
        editor.setText(value or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model = cast(InventoryLinesModel, model)
        key = model.key(index)
        text = editor.text().strip()
        try:
            if key == ACCOUNT:
                value = model.s.catalog.resolve_account(text).id if text else None
            elif key in {SC1, SC2, SC3}:
                kind_id = model.kind_at(index.row(), key)
                if kind_id is None:  # the account has no subconto at this position
                    return
                owner = model.owner_at(index.row(), key)
                value = model.s.catalog.resolve_value(kind_id, text, owner) if text else None
                if text and value is None:
                    self.unknown_value.emit(QPersistentModelIndex(index), kind_id, text)
                    return
            elif key in LIST_KEYS:
                value = _resolve_choice(model.choices(index.row(), key), text) if text else None
                if text and value is None:
                    signal = self.unknown_item if key == ITEM else self.unknown_warehouse
                    signal.emit(QPersistentModelIndex(index), text)
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

    def _commit_and_next(self, editor) -> None:
        if editor.property("inventory_done"):
            return
        editor.setProperty("inventory_done", True)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.EditNextItem)


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
            SC1: 100,
            SC2: 100,
            SC3: 100,
        }
        used = model.s.catalog.used_positions()
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column, key in enumerate(model.columns):
            self.setColumnWidth(column, widths.get(key, 120))
            if key in {SC1, SC2, SC3}:
                self.setColumnHidden(column, int(key[-1]) not in used)
            if key == VAT:
                self.setColumnHidden(column, not model.has_vat())
            if key == CURRENCY_AMOUNT:
                self.setColumnHidden(column, not model.has_currency)
            if key == ITEM:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

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
        self.vat_rate = QComboBox()
        for rate, label in VAT_RATES:
            self.vat_rate.addItem(tr(label), rate)
        meta.addWidget(self.vat_rate)
        meta.addSpacing(12)
        self.currency_caption = QLabel(tr("Валюта"))
        self.currency_caption.setObjectName("secondary")
        meta.addWidget(self.currency_caption)
        self.currency = QComboBox()
        self.currency.addItem("AZN", None)
        for currency in session.catalog.active_currencies:
            self.currency.addItem(currency.code, currency.id)
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

        # a new receipt has VAT when the company has an input VAT account to post it to
        has_vat_account = session.ledger.account_role(session.company_id, INPUT_VAT) is not None
        self._show_vat_rate(STANDARD_VAT_RATE if has_vat_account else None)
        self.model = InventoryLinesModel(session, doc_type, vat_rate=self._chosen_vat_rate())
        self.delegate = InventoryLinesDelegate(self)
        self.table = InventoryLinesTable(self.model, self.delegate)
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
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
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
        self._connect_delegate()
        self.model.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.vat_rate.activated.connect(self._vat_rate_changed)
        self.currency.activated.connect(self._currency_changed)
        self.rate.textEdited.connect(self._rate_edited)
        self.date.dateChanged.connect(self._date_changed)
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
            lambda index, text: QTimer.singleShot(0, lambda: self._create_warehouse(index, text))
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
        if not index.isValid() or not self._ask_add(text, kind):
            return
        owner = self.model.owner_at(index.row(), self.model.columns[index.column()])
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))

    def _create_item(self, index: QPersistentModelIndex, text: str) -> None:
        if not index.isValid():
            return
        dialog = ItemDialog(self.s, self.inventory, self, name=text)
        if dialog.units.count() == 0:
            self.show_error(tr("Сначала добавьте единицу измерения"))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.item_id is None:
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), dialog.item_id)
        self.s.notify(tr("Товар добавлен"))

    def _create_warehouse(self, index: QPersistentModelIndex, text: str) -> None:
        if not index.isValid() or not self._ask_add(text, tr("Склад")):
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

    def _show_vat_rate(self, rate: int | None) -> None:
        index = self.vat_rate.findData(rate)
        if index < 0:  # a rate not in the list (set elsewhere): show it as it is
            self.vat_rate.addItem(f"{Decimal(rate or 0).scaleb(-2).normalize():f}%", rate)
            index = self.vat_rate.count() - 1
        self.vat_rate.setCurrentIndex(index)
        receipt = self.doc_type == "receipt"
        self.vat_caption.setVisible(receipt)
        self.vat_rate.setVisible(receipt)

    def _chosen_vat_rate(self) -> int | None:
        return self.vat_rate.currentData() if self.doc_type == "receipt" else None

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
        shown = self.doc_type == "receipt" and self.model.has_vat()
        self.vat_total_caption.setVisible(shown)
        self.vat_total.setVisible(shown)
        self.vat_total.setText(money(vat, blank_zero=False))
        self.total.setText(money(self.model.total() + vat, blank_zero=False))

    def _changed(self, *_args) -> None:
        self._show_totals()
        if not self.model.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def _set_new(self) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        self._apply_mode(False)
        self._show_currency(None, None)
        self.dirty = False  # showing the defaults is not an edit
        self._show_totals()

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
            )
            for line in self.doc.lines
        ] or [InventoryGridRow()]
        read_only = not self.doc.editable  # a posted document is edited in place, as in 1C
        self.model = InventoryLinesModel(
            self.s, self.doc_type, rows, read_only=read_only, vat_rate=vat_rate
        )
        self.table.setModel(self.model)
        self.table.configure_columns()
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
        self.model.read_only = read_only
        posted = self.doc is not None and self.doc.status == "posted"
        editable = not read_only and self.doc_type != "landed_cost"
        self.btn_save.setVisible(editable and not posted)  # Ctrl+S reposts a posted one
        self.btn_post.setVisible(editable)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(posted and self.doc_type != "landed_cost")
        self.btn_gl.setVisible(self.doc is not None and self.doc.gl_document_id is not None)
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
