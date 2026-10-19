"""Editable multi-line warehouse document and its posted document card."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

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
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    Inventory,
    InventoryDocumentData,
    IssueLine,
    ReceiptLine,
    TransferLine,
    format_quantity,
    to_quantity,
)
from modern_gl.desktop.inventory_page import ItemDialog
from modern_gl.desktop.postings import attach_list
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import Chip, button, date_edit, money, to_qdate
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import fold, tr

ITEM = "item"
WAREHOUSE = "warehouse"
TO_WAREHOUSE = "to_warehouse"
QUANTITY = "quantity"
UNIT = "unit"
PRICE = "price"
AMOUNT = "amount"
ACCOUNT = "account"
SC1 = "sc1"
SC2 = "sc2"
SC3 = "sc3"
MEMO = "memo"
LIST_KEYS = {ITEM, WAREHOUSE, TO_WAREHOUSE, ACCOUNT, SC1, SC2, SC3}

HEADERS = {
    ITEM: "Товар",
    WAREHOUSE: "Склад",
    TO_WAREHOUSE: "Склад-получатель",
    QUANTITY: "Количество",
    UNIT: "Ед.",
    PRICE: "Цена",
    AMOUNT: "Сумма",
    ACCOUNT: "Счёт расчётов / затрат",
    SC1: "Субконто",
    SC2: "",
    SC3: "",
    MEMO: "Комментарий строки",
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
    "Del — удалить строку   ·   Ctrl+S — сохранить   ·   Ctrl+Enter — провести"
)


def _round_ratio(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    return quotient + int(remainder * 2 >= denominator)


@dataclass(frozen=True)
class ItemChoice:
    id: int
    label: str
    unit: str
    precision: int


@dataclass(frozen=True)
class WarehouseChoice:
    id: int
    label: str


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
        )


class InventoryLinesModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        session: Session,
        doc_type: str,
        rows: list[InventoryGridRow] | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self.s = session
        self.doc_type = doc_type
        self.read_only = read_only
        self.items = self._items()
        self.warehouses = self._warehouses()
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
                AMOUNT,
                ACCOUNT,
                SC1,
                SC2,
                SC3,
                MEMO,
            ]

    def _items(self) -> dict[int, ItemChoice]:
        rows = self.s.conn.execute(
            """
            SELECT i.id, v.code, v.name, u.code AS unit_code, u.precision
            FROM inventory_items i
            JOIN subconto_values v ON v.id = i.subconto_value_id
            JOIN inventory_units u ON u.id = i.unit_id
            WHERE i.company_id = ? AND v.active = 1
            ORDER BY v.name
            """,
            (self.s.company_id,),
        )
        return {
            row["id"]: ItemChoice(
                row["id"],
                f"{row['code']}  {row['name']}" if row["code"] else row["name"],
                row["unit_code"],
                row["precision"],
            )
            for row in rows
        }

    def _warehouses(self) -> dict[int, WarehouseChoice]:
        rows = self.s.conn.execute(
            """
            SELECT w.id, v.code, v.name FROM warehouses w
            JOIN subconto_values v ON v.id = w.subconto_value_id
            WHERE w.company_id = ? AND v.active = 1 ORDER BY v.name
            """,
            (self.s.company_id,),
        )
        return {
            row["id"]: WarehouseChoice(
                row["id"],
                f"{row['code']}  {row['name']}" if row["code"] else row["name"],
            )
            for row in rows
        }

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
        return (
            [(value.id, value.label) for value in self.s.catalog.values(kind_id)] if kind_id else []
        )

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
        subconto: list[int | None] = []
        for kind_id in account.sc_kinds:
            values = self.s.catalog.values(kind_id) if kind_id is not None else []
            subconto.append(values[0].id if values else None)
        return InventoryGridRow(
            offset_account_id=account.id,
            offset_subconto=subconto,
        )

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return tr(HEADERS[self.columns[section]])
            return str(section + 1)
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
        if not row.quantity or row.amount is None:
            return None
        return _round_ratio(row.amount * QUANTITY_FACTOR, row.quantity)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row = self.rows[index.row()]
        key = self.key(index)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if key == ITEM:
                if role == Qt.ItemDataRole.EditRole:
                    return row.item_id
                return self.items[row.item_id].label if row.item_id in self.items else ""
            if key in {WAREHOUSE, TO_WAREHOUSE}:
                warehouse_id = row.warehouse_id if key == WAREHOUSE else row.to_warehouse_id
                if role == Qt.ItemDataRole.EditRole:
                    return warehouse_id
                return (
                    self.warehouses[warehouse_id].label if warehouse_id in self.warehouses else ""
                )
            if key == QUANTITY:
                if row.quantity is None:
                    return ""
                precision = self.items[row.item_id].precision if row.item_id in self.items else 6
                return format_quantity(
                    row.quantity, 6 if role == Qt.ItemDataRole.EditRole else precision
                )
            if key == UNIT:
                return self.items[row.item_id].unit if row.item_id in self.items else ""
            if key == PRICE:
                price = self._price(row)
                if price is None:
                    return ""
                return (
                    format_minor(price).replace(" ", "")
                    if role == Qt.ItemDataRole.EditRole
                    else money(price)
                )
            if key == AMOUNT:
                if row.amount is None:
                    return ""
                return (
                    format_minor(row.amount).replace(" ", "")
                    if role == Qt.ItemDataRole.EditRole
                    else money(row.amount)
                )
            if key == ACCOUNT:
                if role == Qt.ItemDataRole.EditRole:
                    return row.offset_account_id
                account = self.s.catalog.accounts.get(row.offset_account_id)
                return account.label if account else ""
            if key in {SC1, SC2, SC3}:
                position = int(key[-1]) - 1
                value_id = row.offset_subconto[position]
                if role == Qt.ItemDataRole.EditRole:
                    return value_id
                if value_id is not None:
                    return self.s.catalog.value(value_id).name
                kind_id = self.kind_at(index.row(), key)
                return self.s.catalog.kinds[kind_id] if kind_id else ""
            return row.memo
        if role == Qt.ItemDataRole.TextAlignmentRole and key in {QUANTITY, PRICE, AMOUNT}:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and key in {SC1, SC2, SC3}:
            if row.offset_subconto[int(key[-1]) - 1] is None:
                return QColor(P.tertiary)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        row = self.rows[index.row()]
        key = self.key(index)
        if key == ITEM:
            row.item_id = value
        elif key == WAREHOUSE:
            row.warehouse_id = value
        elif key == TO_WAREHOUSE:
            row.to_warehouse_id = value
        elif key == QUANTITY:
            row.quantity = value
        elif key == PRICE:
            if not row.quantity:
                raise ValidationError(tr("сначала укажите количество"))
            row.amount = _round_ratio(value * row.quantity, QUANTITY_FACTOR)
        elif key == AMOUNT:
            row.amount = value
        elif key == ACCOUNT:
            row.offset_account_id = value
            kinds = self.s.catalog.accounts[value].sc_kinds if value else (None, None, None)
            for position, kind in enumerate(kinds):
                current = row.offset_subconto[position]
                if current is not None and (
                    kind is None or self.s.catalog.value(current).kind_id != kind
                ):
                    row.offset_subconto[position] = None
        elif key in {SC1, SC2, SC3}:
            row.offset_subconto[int(key[-1]) - 1] = value
        else:
            row.memo = value
        self.dataChanged.emit(
            self.index(index.row(), 0), self.index(index.row(), len(self.columns) - 1)
        )
        self.changed.emit()
        return True

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
        elif key in {QUANTITY, PRICE, AMOUNT}:
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

    def setModelData(self, editor, model: InventoryLinesModel, index):
        key = model.key(index)
        text = editor.text().strip()
        try:
            if key == ACCOUNT:
                value = model.s.catalog.resolve_account(text).id if text else None
            elif key in {SC1, SC2, SC3}:
                kind_id = model.kind_at(index.row(), key)
                value = model.s.catalog.resolve_value(kind_id, text) if text else None
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
            elif key in {PRICE, AMOUNT}:
                value = to_minor(text) if text else None
                if value is not None and value <= 0:
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
        widths = {
            ITEM: 210,
            WAREHOUSE: 150,
            TO_WAREHOUSE: 160,
            QUANTITY: 110,
            UNIT: 65,
            PRICE: 110,
            AMOUNT: 120,
            ACCOUNT: 190,
            SC1: 150,
            SC2: 140,
            SC3: 130,
        }
        for column, key in enumerate(model.columns):
            if key in widths:
                self.setColumnWidth(column, widths[key])
        self.horizontalHeader().setStretchLastSection(True)

    def model(self) -> InventoryLinesModel:
        return super().model()

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
        meta.addStretch(1)
        root.addLayout(meta)

        self.model = InventoryLinesModel(session, doc_type)
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
        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self._grid_shortcut("Ins", self._insert_row, while_editing=True)
        self._grid_shortcut("F9", self._duplicate_row, while_editing=True)
        self._grid_shortcut("Del", self._remove_row)

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
        value_id = self.s.ledger.add_subconto_value(self.s.company_id, kind_id, text)
        self.s.catalog.add_value(value_id, kind_id, text)
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

    def _changed(self, *_args) -> None:
        self.total.setText(money(self.model.total(), blank_zero=False))
        if not self.model.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def _set_new(self) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        self._apply_mode(False)
        self.total.setText(money(0, blank_zero=False))

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.doc_type = self.doc.doc_type
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.type_label.setText(tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type)))
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
            )
            for line in self.doc.lines
        ] or [InventoryGridRow()]
        self.model = InventoryLinesModel(
            self.s, self.doc_type, rows, read_only=self.doc.status == "posted"
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
        self._apply_mode(self.doc.status == "posted")
        self.dirty = False
        self.total.setText(money(self.model.total(), blank_zero=False))
        self.title_changed.emit()

    def _apply_mode(self, read_only: bool) -> None:
        self.memo.setReadOnly(read_only)
        self.memo.setEnabled(not read_only)
        self.date.setEnabled(not read_only)
        self.model.read_only = read_only
        self.btn_save.setVisible(not read_only and self.doc_type != "landed_cost")
        self.btn_post.setVisible(not read_only and self.doc_type != "landed_cost")
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(
            read_only and self.doc is not None and self.doc_type != "landed_cost"
        )
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
            inputs = self.model.to_inputs(complete=post)
            document_id = self._save_draft(inputs)
            if post:
                self.inventory.post_document(self.s.company_id, document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return False
        self.s.working_date = self.date.date().toPython()
        self.load(document_id)
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
        document_date = self.date.date().toPython()
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
                )
            self.inventory.update_receipt_draft(
                company_id,
                self.doc.id,
                document_date,
                inputs,
                first.credit_account_id,
                first.credit_subconto,
                memo,
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
