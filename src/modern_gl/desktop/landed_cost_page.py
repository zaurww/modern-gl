"""«Расходы по партии»: the expenses of a batch of receipts and how they are allocated.

A charge is typed in the document (the carrier's or customs' account, amount, VAT) or is
an existing GL posting (a broker's invoice already on 44…) whose debit moves to stock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
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
    Inventory,
    InventoryDocumentData,
    LandedCostCharge,
    LandedCostTarget,
    allocate_minor,
    format_quantity,
    vat_of,
)
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.postings import (
    TABS,
    CellEditor,
    attach_account_list,
    attach_list,
    edit_current,
    holds_on_group,
    plain_number,
    tabbed_in,
)
from modern_gl.desktop.reports_page import Column, ReportModel
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
from modern_gl.domain.currency import format_unit_rate, parse_rate, to_base, unit_rate
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, round_ratio, to_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.inventory import (
    BatchCostLine,
    CostSource,
    ReceiptLineChoice,
    batch_cost,
    cost_sources,
    landed_cost_type_choices,
    receipt_line_choices,
)

COST_TYPE = "cost_type"
ACCOUNT = "account"
SC1, SC2, SC3 = "sc1", "sc2", "sc3"
AMOUNT = "amount"
CURRENCY_AMOUNT = "currency_amount"
RATE = "rate"
VAT = "vat"
MEMO = "memo"
CHARGE_HEADERS = {
    COST_TYPE: "Статья",
    ACCOUNT: "Счёт",
    SC1: "Субконто",
    SC2: "",
    SC3: "",
    CURRENCY_AMOUNT: "В валюте",
    RATE: "Курс",
    AMOUNT: "Сумма",
    VAT: "НДС",
    MEMO: "Комментарий",
}

DOCUMENT = "document"
ITEM = "item"
WAREHOUSE = "warehouse"
QUANTITY = "quantity"
COST = "cost"
SHARE = "share"
UNIT_COST = "unit_cost"
TARGET_HEADERS = {
    DOCUMENT: "Поступление",
    ITEM: "Товар",
    WAREHOUSE: "Склад",
    QUANTITY: "Количество",
    COST: "Стоимость",
    SHARE: "Расходы",
    UNIT_COST: "Цена с расходами",
}
NUMBER_KEYS = {AMOUNT, CURRENCY_AMOUNT, RATE, VAT, QUANTITY, COST, SHARE, UNIT_COST}

METHODS = [
    ("value", "По стоимости"),
    ("quantity", "По количеству"),
    ("manual", "Вручную"),
]

HINT = (
    "Enter, Tab — дальше   ·   Shift+Tab — назад   ·   "
    "Ins — расход   ·   Del — удалить строку   ·   "
    "Сумма «30 USD» — в валюте   ·   НДС «18%» — посчитать   ·   Ctrl+Enter — провести"
)


@dataclass
class ChargeRow:
    cost_type_id: int | None = None
    account_id: int | None = None
    subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    vat_amount: int | None = None
    source: tuple[int, int] | None = None  # a GL posting: (document id, line number)
    source_label: str = ""
    memo: str = ""
    # an expense in a currency: the manat amount is the currency amount at the rate
    currency_id: int | None = None
    currency_code: str = ""
    currency_amount: int | None = None
    rate: Fraction | None = None
    rate_typed: bool = False  # a new date of the document no longer changes it

    def recalculate(self) -> None:
        if self.currency_id is not None:
            ok = self.currency_amount is not None and self.rate is not None
            self.amount = (
                to_base(self.currency_amount or 0, self.rate or Fraction(0)) if ok else None
            )

    def is_empty(self) -> bool:
        return (
            self.cost_type_id is None
            and self.amount is None
            and self.currency_amount is None
            and self.source is None
            and not self.memo.strip()
        )


@dataclass
class TargetRow:
    receipt: ReceiptLineChoice
    manual: int | None = None
    line_id: int | None = None
    share: int | None = None  # calculated (or the manual amount)


def _resolve(choices: list[tuple[int, str]], text: str) -> int | None:
    needle = fold(text)
    exact = [i for i, label in choices if needle in {fold(label), fold(label.split("  ")[-1])}]
    if exact:
        return exact[0]
    partial = [i for i, label in choices if needle in fold(label)]
    if len(partial) > 1:
        raise LookupError(tr("«{text}» подходит к нескольким", text=text))
    return partial[0] if partial else None


class ChargesModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        session: Session,
        rows: list[ChargeRow],
        read_only: bool,
        rate_of=lambda _currency_id: None,
    ) -> None:
        super().__init__()
        self.s = session
        self.rate_of = rate_of  # currency id -> the rate on the document's date (or None)
        self.read_only = read_only
        self.cost_types = {
            c.id: c.label for c in landed_cost_type_choices(session.conn, session.company_id)
        }
        self.rows = rows or [self.default_row()]
        self.columns = [
            COST_TYPE,
            ACCOUNT,
            SC1,
            SC2,
            SC3,
            CURRENCY_AMOUNT,
            RATE,
            AMOUNT,
            VAT,
            MEMO,
        ]

    def default_row(self) -> ChargeRow:
        account = self.s.catalog.by_code.get("60")
        if account is not None and account.is_group:
            account = next(
                (a for a in self.s.catalog.leaf_accounts if a.code.startswith("60.")), None
            )
        return ChargeRow(account_id=account.id if account else None)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def key(self, index: QModelIndex) -> str:
        return self.columns[index.column()]

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return str(section + 1) if role == Qt.ItemDataRole.DisplayRole else None
        key = self.columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(CHARGE_HEADERS[key]) if CHARGE_HEADERS[key] else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            side = Qt.AlignmentFlag.AlignRight if key in NUMBER_KEYS else Qt.AlignmentFlag.AlignLeft
            return side | Qt.AlignmentFlag.AlignVCenter
        return None

    def kind_at(self, row: int, key: str) -> int | None:
        account_id = self.rows[row].account_id
        if key not in {SC1, SC2, SC3} or account_id is None:
            return None
        return self.s.catalog.accounts[account_id].sc_kinds[int(key[-1]) - 1]

    def owner_at(self, row: int, key: str) -> int | None:
        charge = self.rows[row]
        if key not in {SC1, SC2, SC3} or charge.account_id is None:
            return None
        account = self.s.catalog.accounts[charge.account_id]
        return self.s.catalog.owner_in(account, charge.subconto, int(key[-1]) - 1)

    def editable(self, row: int, key: str) -> bool:
        if self.read_only:
            return False
        charge = self.rows[row]
        if charge.source is not None:  # the account comes from the GL posting
            return key in {COST_TYPE, AMOUNT, MEMO}
        if key == RATE:
            return charge.currency_id is not None
        return key not in {SC1, SC2, SC3} or self.kind_at(row, key) is not None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.editable(index.row(), self.key(index)):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def choices(self, row: int, key: str) -> list[tuple[int, str]] | None:
        if key == COST_TYPE:
            return list(self.cost_types.items())
        if key == ACCOUNT:
            return [(a.id, a.label) for a in self.s.catalog.leaf_accounts]
        if key in {SC1, SC2, SC3}:
            kind = self.kind_at(row, key)
            owner = self.owner_at(row, key)
            return [(v.id, v.label) for v in self.s.catalog.values(kind, owner)] if kind else []
        return None

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        charge = self.rows[index.row()]
        key = self.key(index)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(index.row(), key)
        if role == Qt.ItemDataRole.EditRole:  # what an editor starts with
            if key in {AMOUNT, CURRENCY_AMOUNT} and charge.currency_id is not None:
                amount = format_minor(charge.currency_amount or 0).replace(" ", "")
                return f"{amount} {charge.currency_code}"
            if key in {AMOUNT, VAT}:
                value = charge.amount if key == AMOUNT else charge.vat_amount
                return "" if value is None else format_minor(value).replace(" ", "")
            if key == RATE:
                return "" if charge.rate is None else format_unit_rate(charge.rate)
            if key == MEMO:
                return charge.memo
            if key in {SC1, SC2, SC3} and charge.subconto[int(key[-1]) - 1] is None:
                return ""  # not the kind's name shown as a placeholder
            return self._text(index.row(), key)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in NUMBER_KEYS:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole:
            empty_sc = key in {SC1, SC2, SC3} and charge.subconto[int(key[-1]) - 1] is None
            from_gl = charge.source is not None and key in {ACCOUNT, SC1, SC2, SC3}
            if empty_sc or from_gl or (key == MEMO and not charge.memo and charge.source):
                return QColor(P.tertiary)
        if role == Qt.ItemDataRole.ToolTipRole and charge.source is not None:
            return tr("Проводка: {label}", label=charge.source_label)
        return None

    def _text(self, row: int, key: str) -> str:
        charge = self.rows[row]
        if key == COST_TYPE:
            return self.cost_types.get(charge.cost_type_id, "") if charge.cost_type_id else ""
        if key == ACCOUNT:
            account = self.s.catalog.accounts.get(charge.account_id) if charge.account_id else None
            return account.label if account else ""
        if key in {SC1, SC2, SC3}:
            value_id = charge.subconto[int(key[-1]) - 1]
            if value_id is not None:
                return self.s.catalog.value(value_id).name
            kind = self.kind_at(row, key)
            return self.s.catalog.kinds[kind] if kind else ""
        if key == AMOUNT:
            return money(charge.amount)
        if key == CURRENCY_AMOUNT:
            if charge.currency_id is None or charge.currency_amount is None:
                return ""
            return f"{money(charge.currency_amount)} {charge.currency_code}"
        if key == RATE:
            return "" if charge.rate is None else format_unit_rate(charge.rate)
        if key == VAT:
            return "" if charge.vat_amount is None else money(charge.vat_amount, blank_zero=False)
        return charge.memo or (charge.source_label if charge.source else "")

    def parse(self, row: int, key: str, text: str):
        """The value typed in a cell (None for an empty cell)."""
        text = text.strip()
        if not text:
            return None
        if key in {ACCOUNT, SC1, SC2, SC3, COST_TYPE}:
            return self._lookup(row, key, text)
        if key == VAT and text.endswith("%"):  # "18%": calculate from the amount
            rate = Decimal(plain_number(text[:-1]) or "0")
            return vat_of(self.rows[row].amount or 0, int(rate * 100))
        if key == RATE:
            return unit_rate(parse_rate(plain_number(text)))
        if key in {AMOUNT, CURRENCY_AMOUNT}:
            return self._parse_amount(row, key, text)
        if key == VAT:
            value = to_minor(plain_number(text))
            if value < 0:
                raise ValueError(tr("сумма не может быть отрицательной"))
            return value
        return text

    def _lookup(self, row: int, key: str, text: str) -> int | None:
        """A directory cell: the account, the subconto value or the cost type."""
        if key == ACCOUNT:
            return self.s.catalog.resolve_account(text).id
        if key == COST_TYPE:
            value = _resolve(self.choices(row, key) or [], text)
        else:
            kind = self.kind_at(row, key)
            if kind is None:
                return None
            value = self.s.catalog.resolve_value(kind, text, self.owner_at(row, key))
        if value is None:
            raise LookupError(tr("нет в справочнике: {text}", text=text))
        return value

    def _parse_amount(self, row: int, key: str, text: str) -> tuple[int | None, int]:
        """(currency id or None for manat, amount): «30 USD» is in dollars; a bare number
        is in the line's currency in «В валюте», in manat in «Сумма»."""
        words = text.replace("\u00a0", " ").split()
        currency_id = None
        if len(words) > 1 and words[-1].isalpha():
            currency_id = self.s.catalog.resolve_currency(words[-1]).id
            text = " ".join(words[:-1])
        elif key == CURRENCY_AMOUNT:
            currency_id = self.rows[row].currency_id
        if currency_id is not None and self.rows[row].source is not None:
            raise ValueError(tr("проводка-источник уже в манатах"))
        value = to_minor(plain_number(text))
        if value <= 0:
            raise ValueError(tr("сумма должна быть больше нуля"))
        return currency_id, value

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        charge = self.rows[index.row()]
        key = self.key(index)
        if key == COST_TYPE:
            charge.cost_type_id = value
        elif key == ACCOUNT:
            charge.account_id = value
            kinds = self.s.catalog.accounts[value].sc_kinds if value else (None, None, None)
            for position, kind in enumerate(kinds):
                current = charge.subconto[position]
                if current is not None and (
                    kind is None or self.s.catalog.value(current).kind_id != kind
                ):
                    charge.subconto[position] = None
        elif key in {SC1, SC2, SC3}:
            charge.subconto[int(key[-1]) - 1] = value
        elif key in {AMOUNT, CURRENCY_AMOUNT}:
            self._set_amount(charge, value)
        elif key == RATE:
            charge.rate, charge.rate_typed = value, value is not None
            charge.recalculate()
        elif key == VAT:
            charge.vat_amount = value
        else:
            charge.memo = value or ""
        self.dataChanged.emit(
            self.index(index.row(), 0), self.index(index.row(), len(self.columns) - 1)
        )
        self.changed.emit()
        return True

    def _set_amount(self, charge: ChargeRow, value: tuple[int | None, int] | int | None) -> None:
        """`value`: (currency id, amount), or a manat amount, or None."""
        if value is None or isinstance(value, int):
            currency_id, amount = None, value
        else:
            currency_id, amount = value
        if currency_id is None:
            charge.currency_id, charge.currency_code = None, ""
            charge.currency_amount = charge.rate = None
            charge.amount = amount
            return
        if currency_id != charge.currency_id:
            charge.currency_id = currency_id
            charge.currency_code = next(
                c.code for c in self.s.catalog.active_currencies if c.id == currency_id
            )
            charge.rate, charge.rate_typed = self.rate_of(currency_id), False
        charge.currency_amount = amount
        charge.recalculate()

    def refresh_rates(self) -> None:
        """A new date of the document: the rates nobody typed follow it."""
        for charge in self.rows:
            if charge.currency_id is not None and not charge.rate_typed:
                charge.rate = self.rate_of(charge.currency_id)
                charge.recalculate()
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )
        self.changed.emit()

    def has_currency(self) -> bool:
        return any(charge.currency_id is not None for charge in self.rows)

    def insert_row(self, row: ChargeRow | None = None) -> int:
        if self.rows and self.rows[-1].is_empty() and row is not None:
            self.remove_row(len(self.rows) - 1, keep_one=False)
        at = len(self.rows)
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.append(row or self.default_row())
        self.endInsertRows()
        self.changed.emit()
        return at

    def remove_row(self, at: int, keep_one: bool = True) -> None:
        self.beginRemoveRows(QModelIndex(), at, at)
        del self.rows[at]
        self.endRemoveRows()
        if keep_one and not self.rows:
            self.insert_row()
        self.changed.emit()

    def total(self) -> int:
        return sum(charge.amount or 0 for charge in self.rows)

    def vat_total(self) -> int:
        return sum(charge.vat_amount or 0 for charge in self.rows)

    def to_inputs(self) -> list[LandedCostCharge]:
        return [
            LandedCostCharge(
                None if charge.amount is None else Decimal(charge.amount).scaleb(-MONEY_SCALE),
                charge.account_id,
                tuple(charge.subconto),
                None
                if charge.vat_amount is None
                else Decimal(charge.vat_amount).scaleb(-MONEY_SCALE),
                charge.cost_type_id,
                charge.source[0] if charge.source else None,
                charge.source[1] if charge.source else None,
                charge.memo.strip(),
                charge.currency_id,
                None if charge.rate is None else format_unit_rate(charge.rate),
                None
                if charge.currency_amount is None
                else Decimal(charge.currency_amount).scaleb(-MONEY_SCALE),
            )
            for charge in self.rows
            if not charge.is_empty()
        ]


class TargetsModel(QAbstractTableModel):
    changed = Signal()

    def __init__(self, rows: list[TargetRow], read_only: bool) -> None:
        super().__init__()
        self.rows = rows
        self.read_only = read_only
        self.method = "value"
        self.columns = [DOCUMENT, ITEM, WAREHOUSE, QUANTITY, COST, SHARE, UNIT_COST]

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def key(self, index: QModelIndex) -> str:
        return self.columns[index.column()]

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return str(section + 1) if role == Qt.ItemDataRole.DisplayRole else None
        key = self.columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(TARGET_HEADERS[key])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            side = Qt.AlignmentFlag.AlignRight if key in NUMBER_KEYS else Qt.AlignmentFlag.AlignLeft
            return side | Qt.AlignmentFlag.AlignVCenter
        return None

    def editable(self, row: int, key: str) -> bool:
        return not self.read_only and key == SHARE and self.method == "manual"

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.editable(index.row(), self.key(index)):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def choices(self, row: int, key: str) -> list[tuple[int, str]] | None:
        return None

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        target = self.rows[index.row()]
        key = self.key(index)
        if role == Qt.ItemDataRole.EditRole and key == SHARE:
            return "" if target.manual is None else format_minor(target.manual).replace(" ", "")
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(target, key)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in NUMBER_KEYS:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and key in {DOCUMENT, COST, QUANTITY}:
            return QColor(P.secondary)
        if role == Qt.ItemDataRole.FontRole and key == SHARE:
            return fonts().heading
        return None

    @staticmethod
    def _text(target: TargetRow, key: str) -> str:
        receipt = target.receipt
        if key == DOCUMENT:
            return f"№{receipt.number}  ·  {ru_date(receipt.doc_date)}"
        if key == ITEM:
            return receipt.item_name
        if key == WAREHOUSE:
            return receipt.warehouse_name
        if key == QUANTITY:
            return f"{format_quantity(receipt.quantity, receipt.precision)} {receipt.unit}"
        if key == COST:
            return money(receipt.amount)
        if key == SHARE:
            return money(target.share)
        if key == UNIT_COST and receipt.quantity:  # the price per unit with the expenses
            cost = receipt.amount + (target.share or 0)
            return money(round_ratio(cost * QUANTITY_FACTOR, receipt.quantity))
        return ""

    def parse(self, row: int, key: str, text: str):
        text = text.strip()
        if not text:
            return None
        value = to_minor(plain_number(text))
        if value < 0:
            raise ValueError(tr("сумма не может быть отрицательной"))
        return value

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not self.editable(index.row(), self.key(index)) or role != Qt.ItemDataRole.EditRole:
            return False
        self.rows[index.row()].manual = value
        self.changed.emit()
        return True

    def add(self, receipts: list[ReceiptLineChoice]) -> int:
        have = {target.receipt.id for target in self.rows}
        new = [TargetRow(r) for r in receipts if r.id not in have]
        if new:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(new) - 1)
            self.rows += new
            self.endInsertRows()
            self.changed.emit()
        return len(new)

    def remove_row(self, at: int) -> None:
        self.beginRemoveRows(QModelIndex(), at, at)
        del self.rows[at]
        self.endRemoveRows()
        self.changed.emit()

    def preview(self, method: str, total: int) -> None:
        """What each line takes: the manual amounts, or the total by value / quantity."""
        self.method = method
        for target in self.rows:
            target.share = target.manual if method == "manual" else None
        if method != "manual" and total > 0 and self.rows:
            field_name = "amount" if method == "value" else "quantity"
            weights = [(n, getattr(t.receipt, field_name)) for n, t in enumerate(self.rows)]
            if sum(w for _, w in weights) > 0:
                for n, share in allocate_minor(total, weights).items():
                    self.rows[n].share = share
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            )

    def allocated(self) -> int:
        return sum(target.share or 0 for target in self.rows)

    def to_inputs(self) -> list[LandedCostTarget]:
        return [
            LandedCostTarget(
                target.receipt.id,
                None if target.manual is None else Decimal(target.manual).scaleb(-MONEY_SCALE),
                target.line_id,
            )
            for target in self.rows
        ]


class CellDelegate(QStyledItemDelegate):
    """A line editor with a list for directory cells; Enter or Tab commits and moves on."""

    error = Signal(str)
    # (kind_id, name, owner_id) -> the new element's id: a subconto list offers
    # "+ Добавить «…»", as in the journal (see `attach_list`)
    add_value: Callable[[int, str, int | None], int] | None = None

    def createEditor(self, parent, option, index):
        model = index.model()
        key = model.key(index)
        editor = CellEditor(parent)
        editor.setFrame(False)
        choices = model.choices(index.row(), key)
        if choices is not None and key == ACCOUNT:
            labels = [label for _, label in choices]
            attach_account_list(editor, labels, model.s.catalog, self._chosen)
        elif choices is not None:
            can_add = key in {SC1, SC2, SC3} and self.add_value is not None
            labels = [label for _, label in choices]
            attach_list(editor, labels, True, self._chosen, can_add=can_add)
        elif key in NUMBER_KEYS:
            editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        editor.returnPressed.connect(lambda widget=editor: self._commit_and_next(widget))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        key, text = model.key(index), editor.text().strip()
        kind = model.kind_at(index.row(), key) if key in {SC1, SC2, SC3} else None
        if editor.property("gl_add") and self.add_value is not None and kind is not None:
            model.setData(index, self.add_value(kind, text, model.owner_at(index.row(), key)))
            return
        try:
            value = model.parse(index.row(), model.key(index), editor.text())
            model.setData(index, value)
        except (LedgerError, LookupError, ValueError, ArithmeticError) as exc:
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
        if editor.property("done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("done", True)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, hint)


class LinesTable(QTableView):
    def __init__(self, model: QAbstractTableModel, delegate: CellDelegate) -> None:
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

    def set_widths(self, widths: dict[str, int], stretch: str) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        model = cast(ChargesModel | TargetsModel, self.model())
        for column, key in enumerate(model.columns):
            self.setColumnWidth(column, widths.get(key, 120))
            if key == stretch:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

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


def _list(selection: QAbstractItemView.SelectionMode) -> QTableView:
    table = QTableView()
    table.setObjectName("list")
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(selection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(32)
    return table


class PickerDialog(QDialog):
    """A searchable list to pick several rows from. With `usual`, only the usual rows are
    shown until «Все» is ticked."""

    def __init__(
        self,
        title: str,
        hint: str,
        columns: list[Column],
        rows: list,
        parent=None,
        usual: Callable[[Any], bool] | None = None,
        all_title: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 480)
        self.all_rows = rows
        layout = QVBoxLayout(self)
        text = QLabel(hint)
        text.setObjectName("secondary")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Поиск"))
        self.usual = usual
        self.show_all = QCheckBox(all_title)
        search_bar = QHBoxLayout()
        search_bar.addWidget(self.search, 1)
        search_bar.addWidget(self.show_all)
        self.show_all.setVisible(usual is not None)
        layout.addLayout(search_bar)
        self.model = ReportModel()
        self.columns = columns
        self.table = _list(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setModel(self.model)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        self.show_all.toggled.connect(lambda _on: self._filter(self.search.text()))
        self.table.doubleClicked.connect(lambda _index: self.accept())
        self._filter("")

    def _filter(self, text: str) -> None:
        needle = fold(text.strip())
        usual = self.usual if self.usual and not self.show_all.isChecked() else None
        rows = [row for row in self.all_rows if (usual is None or usual(row))]
        rows = [
            row
            for row in rows
            if not needle
            or needle in fold(" ".join(str(c.get(row)) for c in self.columns if not c.money))
            or needle in format_minor(getattr(row, "amount", 0)).replace(" ", "")
        ]
        self.model.set(self.columns, rows)
        header = self.table.horizontalHeader()
        for n, column in enumerate(self.columns):
            if column.width:
                header.setSectionResizeMode(n, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(n, column.width)
            else:
                header.setSectionResizeMode(n, QHeaderView.ResizeMode.Stretch)
        if rows:
            self.table.selectRow(0)

    def chosen(self) -> list:
        return [self.model.rows[i.row()] for i in self.table.selectionModel().selectedRows()]


def receipt_picker(session: Session, parent=None) -> PickerDialog:
    rows = receipt_line_choices(session.conn, session.company_id)
    columns = [
        Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=96),
        Column("№", lambda r: r.number, width=56),
        Column(tr("Товар"), lambda r: r.item_name),
        Column(tr("Склад"), lambda r: r.warehouse_name, width=130),
        Column(
            tr("Количество"),
            lambda r: format_quantity(r.quantity, r.precision),
            width=100,
            right=True,
        ),
        Column(tr("Стоимость"), lambda r: r.amount, money=True, width=110),
        Column(tr("Комментарий"), lambda r: r.memo, width=180),
    ]
    return PickerDialog(
        tr("Партия: поступления"),
        tr("Выберите строки поступлений (Ctrl / Shift — несколько). Поиск — по товару, номеру…"),
        columns,
        rows,
        parent,
    )


def cost_source_picker(session: Session, exclude: int | None, parent=None) -> PickerDialog:
    rows = cost_sources(session.conn, session.company_id, exclude)
    columns = [
        Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=96),
        Column("№", lambda r: r.number, width=56),
        Column(tr("Дт"), lambda r: r.debit, width=70),
        Column(tr("Кт"), lambda r: r.credit, width=70),
        Column(tr("Субконто"), lambda r: r.subconto, width=150),
        Column(tr("Содержание"), lambda r: r.memo),
        Column(tr("Сумма"), lambda r: r.amount, money=True, width=100),
        Column(tr("Остаток"), lambda r: r.left, money=True, width=100),
    ]
    return PickerDialog(
        tr("Расход из проводки"),
        tr(
            "Уже введённая проводка (фактура брокера, таможни…): её дебет перейдёт в стоимость "
            "товаров. Показан нераспределённый остаток."
        ),
        columns,
        rows,
        parent,
        usual=lambda r: r.debit_class == "expense",
        all_title=tr("Все проводки"),
    )


def source_label(source: CostSource) -> str:
    return f"№{source.number} · {ru_date(source.doc_date)} · {source.debit}/{source.credit}" + (
        f" · {source.memo}" if source.memo else ""
    )


@dataclass
class _CostRow:
    """A line of the batch cost report, or its total."""

    document: str = ""
    item: str = ""
    quantity: str = ""
    price: str = ""
    rate: str = ""
    cost: int = 0
    shares: dict[int, int] = field(default_factory=dict)
    expenses: int = 0
    total: int = 0
    unit_cost: int | None = None
    is_total: bool = False


def _cost_row(line: BatchCostLine) -> _CostRow:
    price = ""
    if line.currency and line.currency_amount is not None and line.quantity:
        unit = round_ratio(line.currency_amount * QUANTITY_FACTOR, line.quantity)
        price = f"{money(unit)} {line.currency}"
    return _CostRow(
        f"№{line.number}  ·  {ru_date(line.doc_date)}",
        line.item_name,
        f"{format_quantity(line.quantity, line.precision)} {line.unit}",
        price,
        "" if line.rate is None else format_unit_rate(unit_rate(line.rate)),
        line.cost,
        line.shares,
        line.expenses,
        line.total,
        round_ratio(line.total * QUANTITY_FACTOR, line.quantity) if line.quantity else None,
    )


class BatchCostDialog(QDialog):
    """«Себестоимость партии»: what each receipt line cost — the supplier's price (in a
    currency and at what rate), every expense separately, the total and a unit's cost."""

    def __init__(self, session: Session, document_id: int, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Себестоимость партии"))
        charges, lines = batch_cost(session.conn, session.company_id, document_id)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setFont(fonts().heading)
        layout.addWidget(heading)
        notes = [
            tr(
                "{title}: {amount} {code} по курсу {rate}",
                title=c.title,
                amount=money(c.currency_amount or 0),
                code=c.currency,
                rate=format_unit_rate(unit_rate(c.rate or 0)),
            )
            for c in charges
            if c.currency
        ]
        if notes:
            note = QLabel("   ·   ".join(notes))
            note.setObjectName("secondary")
            layout.addWidget(note)
        in_currency = any(line.currency for line in lines)
        self.columns = [
            Column(tr("Поступление"), lambda r: r.document, width=1),
            Column(tr("Товар"), lambda r: r.item),
            Column(tr("Количество"), lambda r: r.quantity, width=1, right=True),
            *(
                [
                    Column(tr("Цена поставщика"), lambda r: r.price, width=1, right=True),
                    Column(tr("Курс"), lambda r: r.rate, width=1, right=True),
                ]
                if in_currency
                else []
            ),
            Column(tr("Стоимость"), lambda r: r.cost, money=True, width=1),
            *[
                Column(c.title, lambda r, cid=c.id: r.shares.get(cid, 0), money=True, width=1)
                for c in charges
            ],
            Column(tr("Итого"), lambda r: r.total, money=True, width=1),
            Column(tr("Цена за единицу"), lambda r: r.unit_cost, money=True, width=1),
        ]  # width 1: as wide as the contents; the item takes the rest
        rows = [_cost_row(line) for line in lines]
        total = _CostRow(
            tr("Итого"),
            cost=sum(r.cost for r in rows),
            shares={c.id: sum(r.shares.get(c.id, 0) for r in rows) for c in charges},
            expenses=sum(r.expenses for r in rows),
            total=sum(r.total for r in rows),
            is_total=True,
        )
        self.model = ReportModel()
        self.model.set(
            self.columns,
            [*rows, total],
            emphasis=lambda r: r.is_total,
            total=lambda r: r.is_total,
        )
        table = _list(QAbstractItemView.SelectionMode.SingleSelection)
        table.setModel(self.model)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(70)
        for n, column in enumerate(self.columns):
            mode = QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(n, mode if column.width else QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(table, 1)
        fixed = sum(header.sectionSizeHint(n) for n, c in enumerate(self.columns) if c.width)
        self.resize(min(max(fixed + 320, 900), 1500), 460)
        buttons = QHBoxLayout()
        copy = button(tr("Копировать для Excel"), "flat")
        copy.clicked.connect(self.copy)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        close = button(tr("Закрыть"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def text(self) -> str:
        """The table as tab-separated lines with a header."""
        model = self.model
        lines = ["\t".join(c.title for c in self.columns)]
        for row in range(model.rowCount()):
            cells = [
                str(model.index(row, column).data() or "").replace("\u00a0", "").replace(" ", "")
                if self.columns[column].money
                else str(model.index(row, column).data() or "")
                for column in range(model.columnCount())
            ]
            lines.append("\t".join(cells))
        return "\n".join(lines) + "\n"

    def copy(self) -> None:
        QApplication.clipboard().setText(self.text())


class LandedCostPage(QWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)

    doc_type = "landed_cost"

    def __init__(self, session: Session, document_id: int | None = None) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.doc: InventoryDocumentData | None = None
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        self.memo.setPlaceholderText(tr("Партия: название или номер инвойса"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        meta = QHBoxLayout()
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        self.method = PickBox()
        self.method.setFixedWidth(170)
        for method, title in METHODS:
            self.method.addItem(tr(title), method)
        self.method.setCurrentIndex(0)
        for caption, widget in ((tr("Дата"), self.date), (tr("Распределение"), self.method)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            meta.addWidget(label)
            meta.addWidget(widget)
            meta.addSpacing(12)
        meta.addStretch(1)
        root.addLayout(meta)

        self.delegate = CellDelegate(self)
        self.delegate.error.connect(self.show_error)
        self.delegate.add_value = self._add_value

        charges_bar = QHBoxLayout()
        charges_title = QLabel(tr("Расходы"))
        charges_title.setFont(fonts().heading)
        charges_bar.addWidget(charges_title, 1)
        self.btn_add_charge = button(tr("+ Расход"), "flat", "Ins")
        self.btn_from_gl = button(tr("+ Из проводки…"), "flat")
        charges_bar.addWidget(self.btn_add_charge)
        charges_bar.addWidget(self.btn_from_gl)
        root.addLayout(charges_bar)
        self.charges = ChargesModel(session, [], read_only=False)
        self.charges_table = LinesTable(self.charges, self.delegate)
        root.addWidget(self.charges_table, 1)

        batch_bar = QHBoxLayout()
        batch_title = QLabel(tr("Партия"))
        batch_title.setFont(fonts().heading)
        batch_bar.addWidget(batch_title, 1)
        self.btn_add_receipts = button(tr("+ Поступления…"), "flat")
        batch_bar.addWidget(self.btn_add_receipts)
        root.addLayout(batch_bar)
        self.targets = TargetsModel([], read_only=False)
        self.targets_table = LinesTable(self.targets, self.delegate)
        root.addWidget(self.targets_table, 1)

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
        self.totals: dict[str, QLabel] = {}
        for key, caption in (
            ("vat", "НДС"),
            ("allocated", "Распределено"),
            ("total", "Расходы"),
        ):
            label = QLabel(tr(caption))
            label.setObjectName("secondary")
            value = QLabel()
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(90)
            if key == "total":
                value.setFont(fonts().total)
                value.setMinimumWidth(130)
            summary.addWidget(label)
            summary.addWidget(value)
            summary.addSpacing(16)
            self.totals[key] = value
            self.totals[f"{key}_caption"] = label
        root.addLayout(summary)

        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_report = button(tr("Себестоимость партии"), "flat")
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_report)
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
        self.btn_report.clicked.connect(self.show_report)
        self.btn_add_charge.clicked.connect(self.add_charge)
        self.btn_from_gl.clicked.connect(self.add_from_gl)
        self.btn_add_receipts.clicked.connect(self.add_receipts)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.method.activated.connect(self._changed)
        for keys, callback in (
            ("Ctrl+S", lambda: self.save(post=False)),
            ("Ctrl+Return", lambda: self.save(post=True)),
            ("Ctrl+Enter", lambda: self.save(post=True)),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(callback)
        for table in (self.charges_table, self.targets_table):
            for keys, callback in (("Ins", self.add_charge), ("Del", self._remove_row)):
                shortcut = QShortcut(QKeySequence(keys), table)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(callback)

        self._set_models([], [], read_only=False)
        if document_id is None:
            self.number.setText(tr("Новый"))
            self.status.set(tr("Новый"), "blue")
            self._apply_mode(False)
        else:
            self.load(document_id)

    # ---- page protocol -----------------------------------------------------------------

    @property
    def document_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("inventory_doc", self.document_id) if self.doc else ("new_inventory", id(self))

    def title(self) -> str:
        operation = tr("Расходы по партии")
        title = (
            f"{operation} №{self.doc.number}" if self.doc else tr("Новое: {type}", type=operation)
        )
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.charges_table.setFocus()

    # ---- editing -----------------------------------------------------------------------

    def _set_models(
        self, charges: list[ChargeRow], targets: list[TargetRow], read_only: bool
    ) -> None:
        self.charges = ChargesModel(self.s, charges, read_only, self._rate_of)
        self.targets = TargetsModel(targets, read_only)
        self.charges_table.setModel(self.charges)
        self.targets_table.setModel(self.targets)
        self.charges_table.set_widths(
            {
                COST_TYPE: 130,
                ACCOUNT: 150,
                SC1: 130,
                SC2: 120,
                SC3: 110,
                CURRENCY_AMOUNT: 110,
                RATE: 80,
                AMOUNT: 100,
                VAT: 90,
            },
            MEMO,
        )
        used = self.s.catalog.used_positions()
        for key in (SC2, SC3):
            column = self.charges.columns.index(key)
            self.charges_table.setColumnHidden(column, int(key[-1]) not in used)
        self.targets_table.set_widths(
            {DOCUMENT: 140, WAREHOUSE: 130, QUANTITY: 110, COST: 110, SHARE: 110, UNIT_COST: 130},
            ITEM,
        )
        self.charges.changed.connect(self._changed)
        self.targets.changed.connect(self._changed)
        self._show_currency_columns()
        self._recalculate()

    def _recalculate(self) -> None:
        method = str(self.method.currentData())
        self.targets.preview(method, self.charges.total())
        total, allocated = self.charges.total(), self.targets.allocated()
        self.totals["total"].setText(money(total, blank_zero=False))
        self.totals["vat"].setText(money(self.charges.vat_total(), blank_zero=False))
        self.totals["allocated"].setText(money(allocated, blank_zero=False))
        off = allocated != total and method == "manual"
        self.totals["allocated"].setObjectName("error" if off else "")
        self.totals["allocated"].style().polish(self.totals["allocated"])
        for key in ("vat", "allocated"):
            shown = key != "vat" or bool(self.charges.vat_total())
            self.totals[key].setVisible(shown)
            self.totals[f"{key}_caption"].setVisible(shown)

    def _rate_of(self, currency_id: int) -> Fraction | None:
        found = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        return found.per_unit if found else None

    def _date_changed(self, *_args) -> None:
        self.charges.refresh_rates()  # also marks the page changed

    def _show_currency_columns(self) -> None:
        shown = self.charges.has_currency()
        for key in (CURRENCY_AMOUNT, RATE):
            self.charges_table.setColumnHidden(self.charges.columns.index(key), not shown)

    def _changed(self, *_args) -> None:
        self._show_currency_columns()
        self._recalculate()
        if not self.charges.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        for table in (self.charges_table, self.targets_table):
            if table.state() == QAbstractItemView.State.EditingState and editor is not None:
                table.commitData(editor)
                table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def add_charge(self) -> None:
        if self.charges.read_only:
            return
        row = self.charges.insert_row()
        self.charges_table.setFocus()
        self.charges_table.setCurrentIndex(self.charges.index(row, 0))

    def add_from_gl(self) -> None:
        if self.charges.read_only:
            return
        dialog = cost_source_picker(self.s, self.document_id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        taken = {charge.source for charge in self.charges.rows}
        for source in dialog.chosen():
            if (source.document_id, source.line_no) in taken:
                continue
            self.charges.insert_row(
                ChargeRow(
                    account_id=source.debit_account_id,
                    subconto=list(source.debit_subconto),
                    amount=source.left,
                    source=(source.document_id, source.line_no),
                    source_label=source_label(source),
                )
            )

    def add_receipts(self) -> None:
        if self.targets.read_only:
            return
        dialog = receipt_picker(self.s, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.targets.add(dialog.chosen())

    def _remove_row(self) -> None:
        self._finish_editing()
        if self.charges_table.hasFocus():
            current = self.charges_table.currentIndex()
            if current.isValid() and not self.charges.read_only:
                self.charges.remove_row(current.row())
        elif self.targets_table.hasFocus():
            current = self.targets_table.currentIndex()
            if current.isValid() and not self.targets.read_only:
                self.targets.remove_row(current.row())

    def _add_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        kind = self.s.catalog.kinds[kind_id]
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
        return value_id

    def keyPressEvent(self, event) -> None:
        """Enter in the title, date or method goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # ---- storage -----------------------------------------------------------------------

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.method.setCurrentIndex(max(self.method.findData(self.doc.allocation_method), 0))
        receipts = {r.id: r for r in receipt_line_choices(self.s.conn, self.s.company_id)}
        sources = {
            (c.document_id, c.line_no): c
            for c in cost_sources(self.s.conn, self.s.company_id, self.doc.id, only_left=False)
        }
        charges = [
            ChargeRow(
                charge.cost_type_id,
                charge.account_id,
                list(charge.subconto),
                charge.amount or None,
                charge.vat_amount or None,
                None
                if charge.source_document_id is None
                else (charge.source_document_id, charge.source_line_no or 0),
                self._source_label(charge.source_document_id, charge.source_line_no, sources),
                charge.memo,
                charge.currency_id,
                next(
                    (
                        c.code
                        for c in self.s.catalog.active_currencies
                        if c.id == charge.currency_id
                    ),
                    "",
                ),
                charge.currency_amount,
                None if charge.currency_rate is None else unit_rate(charge.currency_rate),
                rate_typed=True,  # the saved rate stays as it was
            )
            for charge in self.doc.charges
        ]
        manual = self.doc.allocation_method == "manual"
        targets = [
            TargetRow(
                receipts[line.source_receipt_line_id],
                line.amount if manual else None,
                line.id,
            )
            for line in self.doc.lines
            if line.source_receipt_line_id in receipts
        ]
        read_only = not self.doc.editable
        self._set_models(charges, targets, read_only)
        if self.doc.status == "posted":
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self._apply_mode(read_only)
        self.dirty = False
        self.title_changed.emit()

    @staticmethod
    def _source_label(document_id, line_no, sources) -> str:
        source = sources.get((document_id, line_no)) if document_id is not None else None
        return source_label(source) if source is not None else ""

    def _apply_mode(self, read_only: bool) -> None:
        posted = self.doc is not None and self.doc.status == "posted"
        for widget in (self.memo, self.date, self.method):
            widget.setEnabled(not read_only)
        for control in (self.btn_add_charge, self.btn_from_gl, self.btn_add_receipts):
            control.setVisible(not read_only)
        self.btn_save.setVisible(not read_only and not posted)
        self.btn_post.setVisible(not read_only)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(posted and not read_only)
        self.btn_gl.setVisible(self.doc is not None and self.doc.gl_document_id is not None)
        self.btn_report.setVisible(posted)  # the shares exist once it is posted
        self.hint.setVisible(not read_only)

    def save(self, post: bool) -> bool:
        if self.charges.read_only:
            return False
        self._finish_editing()
        self.error.hide()
        try:
            targets, charges = self.targets.to_inputs(), self.charges.to_inputs()
            if not targets:
                raise ValidationError(tr("Добавьте поступления партии"))
            if self.doc is not None and self.doc.status == "posted":
                post = True
                with self.inventory.reposting(self.s.company_id, self.doc.id):
                    document_id = self._save_draft(targets, charges)
            else:
                document_id = self._save_draft(targets, charges)
                if post:
                    self.inventory.post_document(self.s.company_id, document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return False
        self.s.working_date = edited_date(self.date)
        self.load(document_id)
        assert self.doc is not None
        self.s.notify(
            tr(
                "Складской документ №{n} проведён" if post else "Складской документ №{n} сохранён",
                n=self.doc.number,
            )
        )
        self.saved.emit(document_id)
        return True

    def _save_draft(self, targets, charges) -> int:
        method = str(self.method.currentData())
        when = edited_date(self.date)
        memo = self.memo.text().strip()
        if self.doc is None:
            return self.inventory.create_landed_cost_draft(
                self.s.company_id, when, targets, charges, method, memo
            )
        self.inventory.update_landed_cost_draft(
            self.s.company_id, self.doc.id, when, targets, charges, method, memo
        )
        return self.doc.id

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

    def show_report(self) -> None:
        if self.doc is None or self.doc.status != "posted":
            return
        title = f"{self.title().rstrip(' •')}  ·  {self.doc.memo}".rstrip(" ·")
        BatchCostDialog(self.s, self.doc.id, title, self).exec()

    def _open_gl(self) -> None:
        if self.doc is not None and self.doc.gl_document_id is not None:
            self.open_gl_document.emit(self.doc.gl_document_id)
