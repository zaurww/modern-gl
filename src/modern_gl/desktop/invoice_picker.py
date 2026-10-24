"""Several e-qaimə paid by one payment: the open ones of the counterparty, ticked like
to-dos in Things (Space or a click), the payment spread over them oldest first."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import allocate
from modern_gl.application.invoices import OpenInvoice
from modern_gl.desktop.list_table import fit_tree
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, ru_date, tick_icon
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class InvoicePicker(QDialog):
    """`chosen`: (e-qaimə, amount) per ticked one, and what is left of the payment."""

    def __init__(
        self, invoices: Sequence[OpenInvoice], total: int | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.invoices = list(invoices)
        self.total = total or None  # the payment typed before, spread over the ticked
        self.chosen: list[tuple[str, int]] = []
        self.left = 0
        self.setWindowTitle(tr("Несколько e-qaimə"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)
        heading = QLabel(tr("Несколько e-qaimə"))
        heading.setFont(fonts().heading)
        lay.addWidget(heading)
        hint = QLabel(tr("Пробел — отметить; оплата идёт с самой старой."))
        hint.setObjectName("secondary")
        lay.addWidget(hint)
        self.list = QTreeWidget()  # number · date · left to pay, no grid
        self.list.setColumnCount(3)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        fit_tree(self.list, 0)
        lay.addWidget(self.list, 1)
        self.items: list[QTreeWidgetItem] = []
        covered = 0
        for invoice in self.invoices:
            item = QTreeWidgetItem(
                [invoice.invoice, ru_date(invoice.doc_date), format_minor(invoice.amount)]
            )
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setSizeHint(0, QSize(0, 34))  # the height of the program's table rows
            # with a payment typed: the oldest ones it covers are ticked already
            ticked = self.total is not None and covered < self.total
            covered += invoice.amount if ticked else 0
            item.setData(0, Qt.ItemDataRole.UserRole, ticked)
            self.list.addTopLevelItem(item)
            self.items.append(item)
            self._show(item)
        if self.items:
            self.list.setCurrentItem(self.items[0])
        self.list.itemClicked.connect(lambda item, _column: self._toggle(item))
        self.list.installEventFilter(self)  # Space and Enter before the list takes them
        self.summary = QLabel()
        self.summary.setObjectName("secondary")
        lay.addWidget(self.summary)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button(tr("Отмена"))
        ok = button(tr("Готово"), "primary", "Enter")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._done)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self._update()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.list and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space and (item := self.list.currentItem()):
                self._toggle(item)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._done()
                return True
        return super().eventFilter(watched, event)

    def _toggle(self, item: QTreeWidgetItem) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, not item.data(0, Qt.ItemDataRole.UserRole))
        self._show(item)
        self._update()

    @staticmethod
    def _show(item: QTreeWidgetItem) -> None:
        item.setIcon(0, tick_icon(bool(item.data(0, Qt.ItemDataRole.UserRole))))

    def ticked(self) -> list[OpenInvoice]:
        return [
            invoice
            for row, invoice in enumerate(self.invoices)
            if self.items[row].data(0, Qt.ItemDataRole.UserRole)
        ]

    def spread(self) -> tuple[list[tuple[str, int]], int]:
        ticked = self.ticked()
        if self.total is None:  # no payment typed: each one in full
            return [(i.invoice, i.amount) for i in ticked], 0
        paid, left = allocate(self.total, [i.amount for i in ticked])
        return [(i.invoice, p) for i, p in zip(ticked, paid, strict=True) if p], left

    def _update(self) -> None:
        chosen, left = self.spread()
        text = tr(
            "Отмечено: {n} · {sum}", n=len(chosen), sum=format_minor(sum(a for _, a in chosen))
        )
        if self.total is not None:
            text += " · " + tr("оплата {total}", total=format_minor(self.total))
            if left:
                text += " · " + tr("аванс {left}", left=format_minor(left))
        self.summary.setText(text)

    def _done(self) -> None:
        self.chosen, self.left = self.spread()
        if self.chosen:
            self.accept()
