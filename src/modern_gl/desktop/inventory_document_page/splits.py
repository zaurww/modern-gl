"""Splitting a line of the document: in two (F8, «Разделить строку») or over several
months of «Расход за» (D65) — the questions asked and the model told."""

from __future__ import annotations

from PySide6.QtCore import QPersistentModelIndex
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from modern_gl.application.inventory import format_quantity, to_quantity
from modern_gl.application.table_text import plain_number
from modern_gl.desktop.inventory_document_page.columns import EXPENSE_MONTH
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.widgets import money
from modern_gl.domain.dates import earlier_months, month_from_code, month_name
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class SplitPart(InventoryDocumentForm):
    def _split_row(self) -> None:
        """F8 (the hint under the table names it): the current line in two, by a quantity
        (goods) or an amount (a service)."""
        self._finish_editing()
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        row = self.model.rows[current.row()]
        if row.is_empty():
            return
        by_quantity = row.item_id is not None and bool(row.quantity)
        if not by_quantity and not row.amount:
            self.show_error(tr("в строке нет суммы — нечего делить"))
            return
        dialog = SplitLineDialog(self, row.quantity if by_quantity else None, row.amount)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.value is None:
            return
        try:
            if by_quantity:
                new_row = self.model.split_row(current.row(), quantity=dialog.value)
            else:
                new_row = self.model.split_row(current.row(), amount=dialog.value)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.table.setCurrentIndex(self.model.index(new_row, current.column()))

    def _split_months(self, index: QPersistentModelIndex) -> None:
        """«несколько месяцев…» picked in «Расход за» («Доход за»): a line per month."""
        if not index.isValid():
            return
        dialog = MonthRangeDialog(self, self.model.doc_date, income=self.doc_type == "sale")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            rows = self.model.split_by_months(index.row(), dialog.months())
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.table.setCurrentIndex(
            self.model.index(rows[-1], self.model.columns.index(EXPENSE_MONTH))
        )


class SplitLineDialog(QDialog):
    """How much goes to the second line: a quantity of the goods, or an amount of the
    service. The rest stays in the line as it is."""

    def __init__(self, parent: QWidget, quantity: int | None, amount: int | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Разделить строку"))
        self.setMinimumWidth(380)
        self.by_quantity = quantity is not None
        self.value: int | None = None
        form = QFormLayout(self)
        whole = (
            tr("Всего {quantity}", quantity=format_quantity(quantity or 0, 6))
            if self.by_quantity
            else tr("Всего {amount}", amount=money(amount, blank_zero=False))
        )
        form.addRow(QLabel(whole))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("во вторую строку"))
        form.addRow(tr("Количество") if self.by_quantity else tr("Сумма"), self.edit)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.hide()
        form.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        text = plain_number(self.edit.text())
        try:
            self.value = to_quantity(text) if self.by_quantity else to_minor(text)
        except (TypeError, ValueError):
            self.error.setText(tr("введите число"))
            self.error.show()
            return
        self.accept()


class MonthRangeDialog(QDialog):
    """The months an expense is spread over, evenly: from one month to another among the
    twelve before the document's."""

    def __init__(self, parent: QWidget, doc_date: str, income: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            tr("Доход за несколько месяцев") if income else tr("Расход за несколько месяцев")
        )
        self.setMinimumWidth(380)
        form = QFormLayout(self)
        form.addRow(QLabel(tr("Сумма строки делится поровну между месяцами")))
        self.first, self.last = PickBox(), PickBox()
        months = earlier_months(doc_date)
        for box in (self.first, self.last):
            for last_day in months:
                box.addItem(month_name(last_day[:7]), last_day)
        self.first.setCurrentIndex(min(1, len(months) - 1))
        self.last.setCurrentIndex(0)
        form.addRow(tr("Первый месяц"), self.first)
        form.addRow(tr("Последний месяц"), self.last)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def months(self) -> list[str]:
        """The last days of the months chosen, earliest first (the ends in any order)."""
        first, last = sorted((self.first.currentData(), self.last.currentData()))
        return sorted(m for m in earlier_months(_after(last), 24) if first <= m <= last)


def _after(month_end: str) -> str:
    """A day of the month after `month_end`: the range of `earlier_months` includes it."""
    return month_from_code(_next_code(month_end))


def _next_code(month_end: str) -> int:
    year, month = int(month_end[:4]), int(month_end[5:7])
    return (year + 1) * 100 + 1 if month == 12 else year * 100 + month + 1
