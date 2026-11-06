"""Service lines of a purchase made goods: «Товар» chosen in «Вид». The lines a code
or a name could not tell (an e-qaimə's) become new items at once, onto a warehouse."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

from modern_gl.application.inventory import USUAL_UNITS, UsualUnit
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
from modern_gl.desktop.inventory_page.dialogs import FIRST_WAREHOUSE
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import fold, tr


class GoodsLinesPart(InventoryDocumentForm):
    def _connect_goods(self) -> None:
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        self.model.goods_wanted.connect(
            lambda row: QTimer.singleShot(0, lambda: self._make_goods(row))
        )
        self.model.stock_account_wanted.connect(self._set_stock_account)

    def _set_stock_account(self, item_id: int, account_id: int) -> None:
        """Another stock account picked on a goods line: it is the item's, so every
        document of the item is posted again on it (D202). A new name has no documents."""
        if item_id < 0:
            self.model.set_new_item_account(item_id, account_id)
            self.model.rows_changed()
            self.postings.changed()
            return
        try:
            self.inventory.set_item_account(self.s.company_id, item_id, account_id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.error.hide()
        self.model.refresh_choices()
        self.model.rows_changed()
        self.postings.changed()
        self.s.notify(
            tr(
                "«{name}»: счёт запасов — {account}",
                name=self.model.items[item_id].label,
                account=self.s.catalog.accounts[account_id].label,
            )
        )

    def _make_goods(self, row: int) -> None:
        """The line, and the other services not yet charged to an account, as new items
        (an item of the same name is taken): the lines, a unit and a stock account are
        asked once for all."""
        model = self.model
        services = [r for r in range(model.rowCount()) if model.is_service(r)]
        if row not in services:
            return
        lines = [(r, model.rows[r].memo.strip() or tr("Товар")) for r in services]
        chosen = {r for r in services if r == row or model.rows[r].expense_account_id is None}
        dialog = NewNamesDialog(self.s, "", True, self, lines=lines, chosen=chosen)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.checked_rows():
            return
        account = dialog.account.currentData()
        if account is None:
            self.show_error(tr("В плане счетов нет счёта с субконто Товар и Склад"))
            return
        rows, names = dialog.checked_rows(), dict(lines)
        try:
            items = self.inventory.add_named_items(
                self.s.company_id,
                [names[r] for r in rows],
                self._chosen_unit(dialog),
                int(account),
                first_warehouse=tr(FIRST_WAREHOUSE),
            )
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.s.catalog.reload()
        model.refresh_choices()
        model.make_goods(dict(zip(rows, items, strict=True)), self._goods_warehouse())
        self.table.configure_columns()
        self.s.notify(tr("Товарами стали строк: {n}", n=len(rows)))

    @staticmethod
    def _chosen_unit(dialog: NewNamesDialog) -> int | UsualUnit:
        """A unit of the list, or one typed: a usual one by its code, else a new one."""
        box = dialog.unit
        text = box.currentText().strip()
        if box.currentIndex() >= 0 and text == box.itemText(box.currentIndex()):
            return int(box.currentData())
        usual = (UsualUnit(tr(u.code), tr(u.name), u.precision) for u in USUAL_UNITS)
        return next((u for u in usual if fold(u.code) == fold(text)), UsualUnit(text, text))

    def _goods_warehouse(self) -> int | None:
        """The warehouse the other goods of the document come to, else the first one."""
        taken = (row.warehouse_id for row in self.model.rows if row.item_id is not None)
        return next(filter(None, taken), next(iter(self.model.warehouses), None))
