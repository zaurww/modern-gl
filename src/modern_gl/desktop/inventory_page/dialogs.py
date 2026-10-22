"""The item and the warehouse settings: compact dialogs of the stock page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from modern_gl.application.inventory import SALE_ROLE_NAMES, Inventory
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.accounts import INPUT_VAT, SALES_VAT
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction
from modern_gl.reporting.inventory import (
    ItemDetails,
    item_details,
    stock_account_choices,
    unit_choices,
)


def open_item(session: Session, inventory: Inventory, value_id: int, parent=None) -> bool:
    """The item dialog of a directory element that is an item; False if it is none or
    nothing was changed."""
    item = item_details(session.conn, session.company_id, value_id)
    if item is None:
        return False
    dialog = ItemDialog(session, inventory, parent, item=item)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    session.catalog.reload()
    session.notify(tr("Товар сохранён"))
    return True


class ItemDialog(QDialog):
    """A new item, or one to change (`item`): its name, code, group and, while no
    document has it, its unit and stock account."""

    def __init__(
        self,
        session: Session,
        inventory: Inventory,
        parent=None,
        name: str = "",
        item: ItemDetails | None = None,
    ) -> None:
        super().__init__(parent)
        self.s, self.inventory, self.item = session, inventory, item
        self.item_id: int | None = item.id if item else None
        self.caption = tr("Товар") if item else tr("Новый товар")
        self.setWindowTitle(self.caption)
        value = session.catalog.value(item.value_id) if item else None
        form = QFormLayout(self)
        self.name = QLineEdit(value.name if value else name)
        self.code = QLineEdit(value.code or "" if value else "")
        self.group = QComboBox()
        self.group.addItem(tr("— без группы"), None)
        kind = self._item_kind()
        for depth, group in session.catalog.groups(kind) if kind is not None else []:
            self.group.addItem(" " * 2 * depth + group.name, group.id)
        if value is not None and value.parent_id is not None:
            self.group.setCurrentIndex(max(self.group.findData(value.parent_id), 0))
        self.units = QComboBox()
        for unit in unit_choices(session.conn, session.company_id):
            self.units.addItem(unit.label, unit.id)
        self.accounts = QComboBox()
        for account in stock_account_choices(session.conn, session.company_id):
            self.accounts.addItem(account.label, account.id)
        if item is not None:
            self.units.setCurrentIndex(max(self.units.findData(item.unit_id), 0))
            self.accounts.setCurrentIndex(max(self.accounts.findData(item.inventory_account_id), 0))
            if item.used:  # its quantities and postings are in these
                for box in (self.units, self.accounts):
                    box.setEnabled(False)
        form.addRow(tr("Наименование"), self.name)
        form.addRow(tr("Артикул"), self.code)
        if self.group.count() > 1:  # the directory has groups
            form.addRow(tr("Группа"), self.group)
        form.addRow(tr("Единица измерения"), self.units)
        form.addRow(tr("Счёт запасов"), self.accounts)
        if item is not None and item.used:
            note = QLabel(tr("По товару есть документы: единица и счёт не меняются"))
            note.setObjectName("tertiary")
            note.setFont(fonts().small)
            form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _item_kind(self) -> int | None:
        return next((k for k, code in self.s.catalog.kind_codes.items() if code == "item"), None)

    def _save(self) -> None:
        if not self.name.text().strip() or self.units.currentData() is None:
            QMessageBox.warning(self, self.caption, tr("Заполните название и единицу"))
            return
        if self.accounts.currentData() is None:
            QMessageBox.warning(
                self, self.caption, tr("В плане счетов нет счёта с субконто Товар и Склад")
            )
            return
        group = self.group.currentData()
        unit, account = int(self.units.currentData()), int(self.accounts.currentData())
        code = self.code.text().strip() or None
        try:
            if self.item is None:
                self.item_id = self.inventory.add_item(
                    self.s.company_id, self.name.text(), unit, account, code, group_id=group
                )
            else:
                self._update(group, unit, account, code)
        except LedgerError as exc:
            QMessageBox.warning(self, self.caption, str(exc))
            return
        self.accept()

    def _update(self, group: int | None, unit: int, account: int, code: str | None) -> None:
        assert self.item is not None
        cid, value_id, ledger = self.s.company_id, self.item.value_id, self.s.ledger
        with transaction(self.s.conn):
            ledger.update_subconto_value(cid, value_id, self.name.text(), code)
            ledger.set_subconto_value_parent(cid, value_id, group)
            self.inventory.update_item(cid, self.item.id, unit, account)


class InventorySettingsDialog(QDialog):
    """Accounts the warehouse posts to by itself: chosen here, not found by a code."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Настройки склада"))
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        self.input_vat = self._account_list(INPUT_VAT, tr("— не указан —"))
        form.addRow(tr("Счёт НДС к возмещению"), self.input_vat)
        form.addRow(self._hint("Поступление с НДС: Дт этот счёт [поставщик] / Кт счёт расчётов."))
        sale = QLabel(tr("Продажа"))
        sale.setFont(fonts().heading)
        form.addRow(sale)
        self.sale_roles = {
            role: self._account_list(
                role, tr("— счёт покупателя —") if role == SALES_VAT else tr("— не указан —")
            )
            for role in SALE_ROLE_NAMES
        }
        for role, combo in self.sale_roles.items():
            form.addRow(tr(SALE_ROLE_NAMES[role]), combo)
        form.addRow(
            self._hint(
                "Продажа: Дт счёт покупателя / Кт выручка (с НДС, если НДС начисляется "
                "с другого счёта); НДС — Дт счёт начисления / Кт НДС к уплате; "
                "товар — Дт себестоимость / Кт счёт товара."
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _account_list(self, role: str, empty: str) -> QComboBox:
        combo = QComboBox()
        # long account names do not squeeze the labels
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(28)
        combo.addItem(empty, None)
        for account in self.s.catalog.leaf_accounts:
            combo.addItem(account.label, account.id)
        current = self.s.ledger.account_role(self.s.company_id, role)
        combo.setCurrentIndex(max(combo.findData(current), 0))
        return combo

    @staticmethod
    def _hint(text: str) -> QLabel:
        hint = QLabel(tr(text))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        return hint

    def _save(self) -> None:
        try:
            for role, combo in {INPUT_VAT: self.input_vat, **self.sale_roles}.items():
                if combo.currentData() != self.s.ledger.account_role(self.s.company_id, role):
                    self.s.ledger.set_account_role(self.s.company_id, role, combo.currentData())
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Настройки склада"), str(exc))
            return
        self.accept()
