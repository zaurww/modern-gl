"""The reconciliation of the ƏDV deposit account with the portal (D118) shown: each
operation by the portal and by the books with what differs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from modern_gl.application.bank.deposit_reconciliation import (
    BOOKS_ONLY,
    PORTAL_ONLY,
    SAME,
    ReconciledRow,
)
from modern_gl.desktop.list_table import fit_tree
from modern_gl.desktop.theme import P
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import N_, tr

COLUMNS = [N_("Дата"), "Контрагент / содержание", N_("Портал"), N_("Программа"), N_("Состояние")]
STATE = COLUMNS.index(N_("Состояние"))


def signed(amount: int) -> str:
    """+594.00 in, −12.44 out."""
    return ("+" if amount > 0 else "−") + format_minor(abs(amount))


def state(row: ReconciledRow) -> str:
    if row.state == SAME:
        return tr("совпадает")
    if row.state == PORTAL_ONLY:
        return tr("только на портале — нет в программе")
    if row.state == BOOKS_ONLY:
        return tr("только в программе — нет на портале")
    return row.note


class ReconciledRows(QTreeWidget):
    """`document_chosen` — the GL document of the row double-clicked."""

    document_chosen = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels([tr(c) for c in COLUMNS])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        fit_tree(self, 1, STATE)  # the counterparty / the memo, the state
        for column in (2, 3):
            self.headerItem().setTextAlignment(column, Qt.AlignmentFlag.AlignRight)
        self.itemDoubleClicked.connect(self._open)

    def show_rows(self, rows: list[ReconciledRow]) -> None:
        self.clear()
        for row in rows:
            self.addTopLevelItem(self._item(row))

    def _item(self, row: ReconciledRow) -> QTreeWidgetItem:
        op, line = row.op, row.line
        portal = signed(op.net) if op is not None else ""
        books = ""
        if line is not None:
            amount = signed(line.money_in - line.money_out)
            books = tr("№{n}  {amount}", n=line.number, amount=amount)
        who = op.name if op is not None else (line.counterparty or line.memo) if line else ""
        item = QTreeWidgetItem([ru_date(row.day), who, portal, books, state(row)])
        item.setData(0, Qt.ItemDataRole.UserRole, row)
        for column in (2, 3):
            item.setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        for column in (1, STATE):
            item.setToolTip(column, item.text(column))
        if row.state == SAME:  # nothing to look at: quieter (D86)
            for column in range(len(COLUMNS)):
                item.setForeground(column, QColor(P.muted))
        else:
            item.setForeground(STATE, QColor(P.amber))
        return item

    def _open(self, item: QTreeWidgetItem, _column: int) -> None:
        row: ReconciledRow = item.data(0, Qt.ItemDataRole.UserRole)
        if row.line is not None:
            self.document_chosen.emit(row.line.document_id)
