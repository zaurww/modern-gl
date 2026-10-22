"""The lines of a warehouse document as a table model: what each cell shows and takes;
the cells, the clipboard and the inputs of `Inventory` are in their own modules."""

from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import (
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QColor

from modern_gl.application.inventory import (
    format_quantity,
    line_amount,
    unit_price,
    vat_of,
)
from modern_gl.application.queries import remembered_expense, remembered_sale_subconto
from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    EXPENSE,
    HEADERS,
    ITEM,
    MEMO,
    NUMBER_KEYS,
    PARTY_HEADERS,
    PRICE,
    QUANTITY,
    RECEIPT_HEADERS,
    SALE_HEADERS,
    SALE_KEYS,
    SC1,
    SC_KEYS,
    STORED_FIELDS,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    VAT_DOCUMENTS,
    WAREHOUSE,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_document_page.lines_base import (
    InventoryLinesBase,
    by_sale_kinds,
    sale_kinds,
)
from modern_gl.desktop.inventory_document_page.lines_clipboard import LinesClipboard
from modern_gl.desktop.inventory_document_page.lines_inputs import LineInputs
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    money,
)
from modern_gl.domain.currency import to_base
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    ItemChoice,
)

__all__ = ["InventoryLinesBase", "InventoryLinesModel", "by_sale_kinds", "sale_kinds"]


class InventoryLinesModel(LinesClipboard, LineInputs):
    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._column_title(self.columns[section])
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

    def _column_title(self, key: str) -> str:
        if key == CURRENCY_AMOUNT and self.currency_code:
            return tr("Сумма, {code}", code=self.currency_code)
        if key == AMOUNT and self.rate is not None:
            return tr("Сумма, ₼")
        if self.stock_only and key == ITEM:  # goods only (D90)
            return tr(HEADERS[key])
        if self.accounts_hidden and key == SC1 and self.doc_type in PARTY_HEADERS:
            return tr(PARTY_HEADERS[self.doc_type])  # the account is unseen (D90)
        if self.doc_type == "sale" and key in SALE_HEADERS:
            return tr(SALE_HEADERS[key])
        if self.doc_type == "receipt" and key in RECEIPT_HEADERS:
            return tr(RECEIPT_HEADERS[key])
        if key in SALE_KEYS:
            kind_id = self.sale_kind(key)
            return self.s.catalog.kinds[kind_id] if kind_id else ""
        if key in SUBCONTO_KEYS and (key[-1] != "1" or self.accounts_hidden):
            return self._kind_header(key)
        return tr(HEADERS[key])

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
        return None if value is None or not row.quantity else unit_price(value, row.quantity)

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
            total = line_amount(value, row.quantity)
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
            if key in SC_KEYS:
                self._remember_expense(index.row())
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
            self._remember_expense(row_index)

    def _party(self, row: InventoryGridRow) -> int | None:
        """The line's counterparty: its offset subconto from a directory with a VÖEN."""
        catalog = self.s.catalog
        return next(
            (
                value
                for value in row.offset_subconto
                if value is not None and catalog.has_tax_id(catalog.value(value).kind_id)
            ),
            None,
        )

    def _remember_expense(self, row_index: int) -> None:
        """An empty expense account of a purchased service (a fixed asset) takes the one
        the same service had the last time — from this supplier if it was bought from it —
        else this supplier's last service's (D76). One chosen by hand is never replaced."""
        row = self.rows[row_index]
        if (
            self.doc_type != "receipt"
            or row.expense_account_id is not None
            or not self.is_service(row_index)
        ):
            return
        remembered = remembered_expense(self.s.conn, self.s.company_id, row.memo, self._party(row))
        if remembered is None or remembered[0] not in self.s.catalog.accounts:
            return
        row.expense_account_id, subconto = remembered
        row.expense_subconto = list(subconto)
        self._drop_foreign(row.expense_account_id, row.expense_subconto)
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)

    def _remember_sale_subconto(self, row_index: int) -> None:
        """Empty sale subconto of a line take what the item (the service) had the last
        time it was sold — to this customer if it was — else what the line above has."""
        row = self.rows[row_index]
        if not self.sale_kinds or None not in row.sale_subconto[: len(self.sale_kinds)]:
            return
        catalog = self.s.catalog
        remembered = (
            remembered_sale_subconto(
                self.s.conn, self.s.company_id, row.item_id, row.memo, self._party(row)
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
