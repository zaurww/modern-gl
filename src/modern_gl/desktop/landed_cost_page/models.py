"""The expenses and the receipt lines of the batch as table models."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor

from modern_gl.application.inventory import (
    LandedCostCharge,
    LandedCostTarget,
    allocate_minor,
    format_quantity,
    unit_price,
    vat_of,
)
from modern_gl.desktop.cell_editing import resolve_choice
from modern_gl.desktop.landed_cost_page.columns import (
    ACCOUNT,
    AMOUNT,
    CHARGE_HEADERS,
    COST,
    COST_TYPE,
    CURRENCY_AMOUNT,
    DOCUMENT,
    ITEM,
    MEMO,
    NUMBER_KEYS,
    QUANTITY,
    RATE,
    SC1,
    SC2,
    SC3,
    SHARE,
    TARGET_HEADERS,
    UNIT_COST,
    VAT,
    WAREHOUSE,
    ChargeRow,
    TargetRow,
)
from modern_gl.desktop.postings import (
    plain_number,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    money,
)
from modern_gl.domain.currency import format_unit_rate, parse_rate, unit_rate
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    ReceiptLineChoice,
    landed_cost_type_choices,
)


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
        # a warehouse only (D90): the supplier's account is put in by itself, unseen
        self.accounts_hidden = session.stock_only and self.default_row().account_id is not None
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
            if key == SC1 and self.accounts_hidden:
                return tr("Поставщик")
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
            value = resolve_choice(self.choices(row, key) or [], text)
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
            return money(unit_price(cost, receipt.quantity) or 0)
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
