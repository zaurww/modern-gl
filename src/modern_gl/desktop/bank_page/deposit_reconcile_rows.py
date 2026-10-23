"""The reconciliation of the ƏDV deposit account with the portal (D118) shown: each
operation by the portal and by the books with what differs, and the period's figures by
both sides with the difference."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from modern_gl.application.bank.deposit_reconciliation import (
    BOOKS_ONLY,
    PORTAL_ONLY,
    SAME,
    DepositReconciliation,
    Figures,
    ReconciledRow,
)
from modern_gl.desktop.theme import P, fonts
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

COLUMNS = ["Дата", "Контрагент / содержание", "Портал", "Программа", "Состояние"]
STATE = COLUMNS.index("Состояние")


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
        header = self.header()
        for column, width in enumerate((96, 0, 110, 150, 0)):
            if width:
                self.setColumnWidth(column, width)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
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


class FiguresGrid(QWidget):
    """Портал / Программа / Разница × на начало, приход, расход, на конец."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(4)
        captions = (tr("На начало"), tr("Приход"), tr("Расход"), tr("На конец"))
        for column, caption in enumerate(captions, 1):
            label = QLabel(caption)
            label.setObjectName("tertiary")
            label.setFont(fonts().small)
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(label, 0, column)
        self.cells: dict[tuple[int, int], QLabel] = {}
        for r, side in enumerate((tr("Портал"), tr("Программа"), tr("Разница")), 1):
            grid.addWidget(QLabel(side), r, 0)
            for column in range(1, 5):
                cell = QLabel()
                font = QFont(fonts().table)
                if r == 3:  # the difference: what to look at
                    font.setWeight(QFont.Weight.DemiBold)
                cell.setFont(font)
                cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                grid.addWidget(cell, r, column)
                self.cells[(r, column)] = cell
        grid.setColumnStretch(5, 1)

    def show_figures(self, seen: DepositReconciliation) -> None:
        def values(f: Figures) -> tuple[int, int, int, int]:
            return f.opening, f.money_in, f.money_out, f.closing

        portal, books = values(seen.portal), values(seen.books)
        for column in range(4):
            diff = portal[column] - books[column]
            self.cells[(1, column + 1)].setText(format_minor(portal[column]))
            self.cells[(2, column + 1)].setText(format_minor(books[column]))
            cell = self.cells[(3, column + 1)]
            cell.setText(format_minor(diff) if diff else "—")
            cell.setObjectName("warning" if diff else "")
            cell.style().unpolish(cell)
            cell.style().polish(cell)
