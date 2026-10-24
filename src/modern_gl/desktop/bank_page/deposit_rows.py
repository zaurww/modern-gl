"""The portal's ƏDV deposit operations in the window before they are written (what each
becomes, ticked to load) and after (what became of each, a double click opens it) — as the
e-qaimə window shows its lines."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from modern_gl.application.bank import IN
from modern_gl.application.bank.deposit_commands import DRAFT, KNOWN, LINKED, POSTED, DepositRow
from modern_gl.desktop.list_table import fit_tree
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr

COLUMNS = ["Дата", "Контрагент", "VÖEN", "Приход", "Расход", "Станет", "Состояние"]
BECOMES, STATE = COLUMNS.index("Станет"), COLUMNS.index("Состояние")
CHOICES = (POSTED, DRAFT, LINKED)  # what can be left out; KNOWN is in the books already


def becomes(row: DepositRow) -> str:
    """'62.1 · MT260411000001 540.00; 62.1 · MT260812000002 54.00' — the account, the
    e-qaimə the money closes, the amount when there is more than one line."""
    parts = []
    for code, invoice, amount in row.lines:
        text = " · ".join(x for x in (code or tr("счёт не определён"), invoice) if x)
        if len(row.lines) > 1:
            text += f" {money(amount)}"
        parts.append(text)
    return "; ".join(parts)


def state(row: DepositRow, written: bool) -> str:
    """What the import does with the operation — or, `written`, what it did."""
    if row.state == KNOWN:
        return tr("уже есть")
    if row.state == LINKED:
        return tr("введена вручную — связана") if written else tr("введена вручную — будет связана")
    if row.state == POSTED:
        return tr("проведена") if written else tr("новая — будет проведена")
    return tr("черновик: {why}", why=row.reason)


class DepositRows(QTreeWidget):
    """The rows of a preview (ticked, the ones in the books greyed) or of an import done
    (`document_chosen` — the GL document of the row double-clicked)."""

    document_chosen = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels([tr(c) for c in COLUMNS])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        fit_tree(self, COLUMNS.index("Контрагент"), BECOMES, STATE)
        for column in (3, 4):
            self.headerItem().setTextAlignment(column, Qt.AlignmentFlag.AlignRight)
        self.itemDoubleClicked.connect(self._open)

    def show_rows(self, rows: list[DepositRow], written: bool) -> None:
        self.clear()
        for row in rows:
            self.addTopLevelItem(self._item(row, written))

    def _item(self, row: DepositRow, written: bool) -> QTreeWidgetItem:
        op = row.op
        item = QTreeWidgetItem(
            [
                ru_date(op.day),
                op.name,
                op.tin,
                money(op.amount) if op.direction == IN else "",
                "" if op.direction == IN else money(op.amount),
                becomes(row),
                state(row, written),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, row)
        for column in (1, BECOMES, STATE):  # a long name, many e-qaimə, a reason in full
            item.setToolTip(column, item.text(column))
        for column in (3, 4):
            item.setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        if not written and row.state in CHOICES:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
        if row.state == KNOWN or (written and row.state == POSTED):
            for column in range(len(COLUMNS)):  # nothing to do here: quieter (D86)
                item.setForeground(column, QColor(P.muted if written else P.tertiary))
        if row.state == DRAFT:
            item.setForeground(STATE, QColor(P.amber))
        if row.document_id is not None:
            hint = tr("Двойной щелчок — открыть документ")
            item.setToolTip(STATE, f"{item.text(STATE)}\n{hint}")
        return item

    def rows(self, ticked_only: bool = False) -> list[DepositRow]:
        found = []
        for n in range(self.topLevelItemCount()):
            item = self.topLevelItem(n)
            if item is None:
                continue
            row: DepositRow = item.data(0, Qt.ItemDataRole.UserRole)
            checkable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            if ticked_only and checkable and item.checkState(0) != Qt.CheckState.Checked:
                continue
            found.append(row)
        return found

    def taken(self) -> set[str]:
        """The references of the operations ticked."""
        return {row.op.reference for row in self.rows(ticked_only=True) if row.state in CHOICES}

    def _open(self, item: QTreeWidgetItem, _column: int) -> None:
        row: DepositRow = item.data(0, Qt.ItemDataRole.UserRole)
        if row.document_id is not None:
            self.document_chosen.emit(row.document_id)
