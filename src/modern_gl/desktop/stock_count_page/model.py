"""The lines of a count: each item with what the books hold and what was counted. The
counted quantity starts as the books' (as 1C «Заполнить»): only a difference is typed."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal

from modern_gl.application.inventory import CountedLine, format_quantity, to_quantity
from modern_gl.desktop.widgets import money
from modern_gl.domain.money import round_ratio, to_minor
from modern_gl.i18n import tr

ITEM, UNIT, BOOK, QUANTITY, DIFFERENCE, AMOUNT = (
    "item",
    "unit",
    "book",
    "quantity",  # the counted quantity: typed
    "difference",
    "amount",  # the value of the difference; a surplus's may be typed
)
COLUMNS = [ITEM, UNIT, BOOK, QUANTITY, DIFFERENCE, AMOUNT]
HEADERS = {
    ITEM: "Товар",
    UNIT: "Ед.",
    BOOK: "По учёту",
    QUANTITY: "Факт",
    DIFFERENCE: "Разница",
    AMOUNT: "Сумма разницы",
}
NUMBERS = {BOOK, QUANTITY, DIFFERENCE, AMOUNT}


@dataclass
class CountRow:
    item_id: int
    name: str
    unit: str
    precision: int
    book: int  # quantity in the books that day (millionths)
    value: int  # their value (minor units)
    counted: int  # millionths
    amount: int | None = None  # a surplus's value, typed

    @property
    def difference(self) -> int:
        return self.counted - self.book

    def difference_value(self) -> int | None:
        """+ a surplus, − a shortage, at the average of what is on hand; a typed amount
        for a surplus; None — a surplus with nothing on hand to price it by."""
        if self.amount is not None and self.difference > 0:
            return self.amount
        if not self.difference:
            return 0
        if self.book <= 0 or self.value <= 0:
            return None
        return round_ratio(self.value * self.difference, self.book)


class CountModel(QAbstractTableModel):
    changed = Signal()

    def __init__(self, rows: list[CountRow] | None = None) -> None:
        super().__init__()
        self.rows = rows or []
        self.columns = COLUMNS
        self.read_only = False

    def set_rows(self, rows: list[CountRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        self.changed.emit()

    def add_row(self, row: CountRow) -> int:
        for at, existing in enumerate(self.rows):
            if existing.item_id == row.item_id:
                return at
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()
        self.changed.emit()
        return len(self.rows) - 1

    # ---- what the shared cell delegate asks (landed_cost_page.table) ------------------

    def key(self, index: QModelIndex | QPersistentModelIndex) -> str:
        return self.columns[index.column()]

    def choices(self, _row: int, _key: str) -> None:
        return None  # no cell offers a list

    def parse(self, row_index: int, key: str, text: str) -> int | None:
        text = text.strip()
        if key == QUANTITY:
            return to_quantity(text or "0")
        return to_minor(text) if text else None

    # ---- Qt ----------------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        key = self.columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(HEADERS[key])
        if role == Qt.ItemDataRole.TextAlignmentRole and key in NUMBERS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.read_only:
            return flags
        key, row = self.key(index), self.rows[index.row()]
        if key == QUANTITY or (key == AMOUNT and row.difference > 0):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        row, key = self.rows[index.row()], self.key(index)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in NUMBERS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.EditRole:
            if key == QUANTITY:
                return format_quantity(row.counted, row.precision)
            if key == AMOUNT:
                value = row.difference_value()
                return "" if value is None else money(value, blank_zero=True)
            return None
        if role == Qt.ItemDataRole.ToolTipRole and key == AMOUNT and self._unpriced(row):
            return tr("Остатка нет — впишите, сколько стоят излишки")
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._text(row, key)

    @staticmethod
    def _unpriced(row: CountRow) -> bool:
        return row.difference > 0 and row.difference_value() is None

    def _text(self, row: CountRow, key: str) -> str:
        if key == ITEM:
            return row.name
        if key == UNIT:
            return row.unit
        if key == BOOK:
            return format_quantity(row.book, row.precision) if row.book else ""
        if key == QUANTITY:
            return format_quantity(row.counted, row.precision)
        if key == DIFFERENCE:
            if not row.difference:
                return ""
            sign = "+" if row.difference > 0 else "−"
            return sign + format_quantity(abs(row.difference), row.precision)
        value = row.difference_value()
        if value is None:
            return tr("впишите сумму")
        return money(value, blank_zero=True)

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or self.read_only:
            return False
        row, key = self.rows[index.row()], self.key(index)
        if key == QUANTITY:
            if value is None or value < 0:
                raise ValueError(tr("фактическое количество не может быть меньше нуля"))
            row.counted = value
        elif key == AMOUNT:
            row.amount = value
        else:
            return False
        first, last = self.index(index.row(), 0), self.index(index.row(), len(self.columns) - 1)
        self.dataChanged.emit(first, last)
        self.changed.emit()
        return True

    # ---- the count -----------------------------------------------------------------

    def counted(self) -> list[CountedLine]:
        """The lines that differ from the books, as the count is posted."""
        return [
            CountedLine(
                r.item_id,
                format_quantity(r.counted, 6),
                None if r.amount is None or r.difference <= 0 else Decimal(r.amount).scaleb(-2),
            )
            for r in self.rows
            if r.difference
        ]

    def totals(self) -> tuple[int, int, int, int]:
        """(lines in surplus, their value, lines short, their value)."""
        surplus = [r for r in self.rows if r.difference > 0]
        short = [r for r in self.rows if r.difference < 0]
        return (
            len(surplus),
            sum(r.difference_value() or 0 for r in surplus),
            len(short),
            -sum(r.difference_value() or 0 for r in short),
        )
