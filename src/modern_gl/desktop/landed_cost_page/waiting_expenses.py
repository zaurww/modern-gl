"""What the books hold for a batch: services of purchases and postings that wait on an account
of procurement (D211). The accountant ticks them; accounts stay out of sight."""

from __future__ import annotations

from collections.abc import Collection

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from modern_gl.desktop.landed_cost_page.columns import ChargeRow
from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.widgets import caption, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import N_, fold, tr
from modern_gl.reporting.inventory import WaitingExpense

DATE, PARTY, MEMO, AMOUNT = range(4)
HEADERS = (N_("Дата"), N_("Поставщик"), N_("Содержание"), N_("Сумма"))
_ROOT = QModelIndex()


def label_of(row: WaitingExpense) -> str:
    return " · ".join(part for part in (ru_date(row.doc_date), row.party, row.memo) if part)


def charge_of(row: WaitingExpense) -> ChargeRow:
    """A line of the batch that takes what is left of it."""
    return ChargeRow(
        account_id=row.account_id,
        subconto=list(row.subconto),
        amount=row.left,
        source=row.source,
        source_label=label_of(row),
        source_line=row.line_id,
    )


def twin_of(charge: ChargeRow, rows: list[WaitingExpense]) -> WaitingExpense | None:
    """The waiting expense a typed one repeats: the same sum. The name is no help: the same
    carrier is «166 YUK TAKSI» by hand and «YÜK TAKSİSİ.AZ MMC» on its e-qaimə."""
    if charge.taken or not charge.amount:
        return None
    return next((row for row in rows if row.waits and row.left == charge.amount), None)


def ask_twin(parent, twin: WaitingExpense) -> QMessageBox.StandardButton:
    """Yes — take it instead; No — they are two expenses; Cancel — go back."""
    return QMessageBox.question(
        parent,
        tr("Расход уже есть в книгах"),
        tr(
            "{amount} уже ждёт партии: {label}.\n\n"
            "Если ввести его ещё раз, долг поставщику задвоится. Взять этот расход вместо "
            "введённого?",
            amount=money(twin.left),
            label=label_of(twin),
        ),
        QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes,
    )


class _Rows(QAbstractTableModel):
    """The expenses with a tick each; what is ticked outlives the search."""

    def __init__(self, ticked: set[tuple]) -> None:
        super().__init__()
        self.rows: list[WaitingExpense] = []
        self.ticked = ticked

    def show(self, rows: list[WaitingExpense]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(HEADERS[section])
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == DATE else flags

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == DATE:
            on = row.key in self.ticked
            return Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == AMOUNT:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.DisplayRole:
            return (ru_date(row.doc_date), row.party, row.memo, money(row.left))[index.column()]
        return None

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.CheckStateRole:
            return False
        key = self.rows[index.row()].key
        if Qt.CheckState(value) == Qt.CheckState.Checked:
            self.ticked.add(key)
        else:
            self.ticked.discard(key)
        self.dataChanged.emit(index, index)
        return True


class WaitingExpensesDialog(QDialog):
    def __init__(
        self, rows: list[WaitingExpense], numbers: Collection[str] = (), parent=None
    ) -> None:
        """`numbers` — the declarations of the batch: what names one comes ticked."""
        super().__init__(parent)
        self.setWindowTitle(tr("Расходы, ждущие партии"))
        self.resize(860, 480)
        self.rows = rows
        wanted = [number for number in numbers if number]
        self.ticked = {row.key for row in rows if any(n in row.memo for n in wanted)}
        root = QVBoxLayout(self)
        hint = caption(
            tr(
                "Отмеченные войдут в стоимость партии: новый долг не появится. Вводите вручную "
                "только то, чего здесь нет, например таможенные платежи."
            )
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Поиск"))
        self.show_all = QCheckBox(tr("Все расходы"))
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_all)
        root.addLayout(bar)
        self.model = _Rows(self.ticked)
        self.table = ListTable(self.model, 32, fill=MEMO)
        self.table.setColumnWidth(DATE, 130)
        self.table.setColumnWidth(PARTY, 230)
        self.table.setColumnWidth(AMOUNT, 110)
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Взять отмеченные"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.search.textChanged.connect(lambda _text: self._fill())
        self.show_all.toggled.connect(lambda _on: self._fill())
        self.show_all.setChecked(not any(row.waits for row in rows))
        self._fill()
        self.search.setFocus()

    def _fill(self) -> None:
        """What waits for a batch; ticked, an expense stays whatever the search says."""
        needle = fold(self.search.text().strip())
        self.model.show(
            [
                row
                for row in self.rows
                if (row.waits or self.show_all.isChecked())
                and (
                    row.key in self.ticked
                    or not needle
                    or needle in fold(f"{row.party} {row.memo} {row.invoice}")
                )
            ]
        )

    def chosen(self) -> list[WaitingExpense]:
        return [row for row in self.rows if row.key in self.ticked]
