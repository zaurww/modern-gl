"""The item and the warehouse settings: compact dialogs of the stock page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from modern_gl.application.inventory import (
    INCOMING_REASONS,
    SALE_ACCOUNT_ROLES,
    SALE_ROLE_NAMES,
    USUAL_UNITS,
    Inventory,
    UsualUnit,
    format_quantity,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.accounts import INPUT_VAT, SALES_VAT
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import N_, tr
from modern_gl.reporting.inventory import (
    ItemDetails,
    item_details,
    last_stock_account,
    sale_account_rows,
    stock_account_choices,
    unit_choices,
    unit_codes,
    warehouse_choices,
)

FIRST_WAREHOUSE = "Основной склад"  # made with the first item of a company without one


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
        self.code.setPlaceholderText(tr("необязательно"))  # a name is enough
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
        if item is None:  # the usual ones too: made with the item that takes one
            self._offer_usual_units()
        self.accounts = QComboBox()
        for account in stock_account_choices(session.conn, session.company_id):
            self.accounts.addItem(account.label, account.id)
        if item is None:  # as the item before it: goods after goods, not the first account
            last = last_stock_account(session.conn, session.company_id)
            self.accounts.setCurrentIndex(max(self.accounts.findData(last), 0))
        else:
            self.units.setCurrentIndex(max(self.units.findData(item.unit_id), 0))
            self.accounts.setCurrentIndex(max(self.accounts.findData(item.inventory_account_id), 0))
            if item.used:  # its quantities are in the unit; the account moves its postings
                self.units.setEnabled(False)
        form.addRow(tr("Наименование"), self.name)
        form.addRow(tr("Артикул"), self.code)
        if self.group.count() > 1:  # the directory has groups
            form.addRow(tr("Группа"), self.group)
        form.addRow(tr("Единица измерения"), self.units)
        self.minimum = QLineEdit(
            format_quantity(item.min_quantity, item.precision) if item and item.min_quantity else ""
        )
        self.minimum.setPlaceholderText(tr("не задан"))
        self.minimum.setToolTip(
            tr("Меньше этого на всех складах — «Bu gün» напомнит купить, «Склад» покажет")
        )
        form.addRow(tr("Минимальный остаток"), self.minimum)
        if not session.stock_only:  # a warehouse only (D90): the first stock account, unseen
            form.addRow(tr("Счёт запасов"), self.accounts)
        self._add_notes(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _add_notes(self, form: QFormLayout) -> None:
        """What saving does beyond the item: a beginner's first item makes the first
        warehouse too; a used one keeps its unit and account."""
        item = self.item
        self.first_warehouse = item is None and not warehouse_choices(
            self.s.conn, self.s.company_id
        )
        notes = []
        if self.first_warehouse:
            notes.append(tr("Вместе с товаром появится склад «{name}»", name=tr(FIRST_WAREHOUSE)))
        if item is not None and item.used:
            notes.append(
                tr(
                    "По товару есть документы: единица не меняется; "
                    "со сменой счёта они проведутся заново"
                )
            )
        for text in notes:
            note = QLabel(text)
            note.setObjectName("tertiary")
            note.setFont(fonts().small)
            form.addRow(note)

    def _offer_usual_units(self) -> None:
        """The usual units the company has no code of; the first unit there is chosen."""
        taken = unit_codes(self.s.conn, self.s.company_id)
        for usual in USUAL_UNITS:
            unit = UsualUnit(tr(usual.code), tr(usual.name), usual.precision)
            if unit.code not in taken:
                self.units.addItem(f"{unit.code}  {unit.name}", unit)
        self.units.setCurrentIndex(0)

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
        group, unit = self.group.currentData(), self.units.currentData()
        account = int(self.accounts.currentData())
        code = self.code.text().strip() or None
        try:
            if self.item is None:
                self.item_id = self.inventory.add_new_item(
                    self.s.company_id,
                    self.name.text(),
                    unit if isinstance(unit, UsualUnit) else int(unit),
                    account,
                    code,
                    group_id=group,
                    first_warehouse=tr(FIRST_WAREHOUSE) if self.first_warehouse else None,
                    min_quantity=self.minimum.text().strip() or None,
                )
            else:
                self._update(group, int(unit), account, code)
        except (LedgerError, ValueError) as exc:  # a minimum that is no number
            QMessageBox.warning(self, self.caption, str(exc))
            return
        self.accept()

    def _update(self, group: int | None, unit: int, account: int, code: str | None) -> None:
        assert self.item is not None
        self.inventory.edit_item(
            self.s.company_id,
            self.item.id,
            self.name.text(),
            code,
            group,
            unit,
            account,
            self.minimum.text().strip() or None,
        )


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
        form.addRow(
            self._hint(N_("Поступление с НДС: Дт этот счёт [поставщик] / Кт счёт расчётов."))
        )
        sale = QLabel(tr("Продажа"))
        sale.setFont(fonts().heading)
        form.addRow(sale)
        self.sale_roles = {
            role: self._account_list(
                role,
                tr("— счёт покупателя —") if role == SALES_VAT else tr("— не указан —"),
                width=18 if role in SALE_ACCOUNT_ROLES else 28,
            )
            for role in SALE_ROLE_NAMES
        }
        self._build_sale_accounts(form)
        for role, combo in self.sale_roles.items():
            if role not in SALE_ACCOUNT_ROLES:  # those are in the table above
                form.addRow(tr(SALE_ROLE_NAMES[role]), combo)
        self._build_incoming(form)
        form.addRow(
            self._hint(
                N_(
                    "Продажа: Дт счёт покупателя / Кт выручка (с НДС, если НДС начисляется "
                    "с другого счёта); НДС — Дт счёт начисления / Кт НДС к уплате; "
                    "товар — Дт себестоимость / Кт счёт товара."
                )
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _build_sale_accounts(self, form: QFormLayout) -> None:
        """The table of the sale accounts: the revenue and the cost of sales of the whole
        company, and under them the stock accounts — the goods of one (41) may be sold on
        other accounts than the materials of another (10). The warehouse's own table."""
        self.sale_accounts: dict[tuple[int, str], QComboBox] = {}
        grid = QGridLayout()
        for column, role in enumerate(SALE_ACCOUNT_ROLES, 1):
            head = QLabel(tr(SALE_ROLE_NAMES[role]))
            head.setObjectName("tertiary")
            head.setFont(fonts().small)
            grid.addWidget(head, 0, column)
            grid.setColumnStretch(column, 1)
            grid.addWidget(self.sale_roles[role], 1, column)
        grid.addWidget(QLabel(tr("Общий счёт")), 1, 0)
        rows = sale_account_rows(self.s.conn, self.s.company_id)
        for line, row in enumerate(rows, 2):
            grid.addWidget(QLabel(row.stock_account.label), line, 0)
            for column, role in enumerate(SALE_ACCOUNT_ROLES, 1):
                combo = self._account_combo(tr("— общий —"), row.own.get(role), width=18)
                self.sale_accounts[row.stock_account.id, role] = combo
                grid.addWidget(combo, line, column)
        form.addRow(grid)
        if rows:
            form.addRow(
                self._hint(
                    N_(
                        "У товаров счёта запасов могут быть свои счета продажи. После "
                        "смены продажи открытого периода проведутся заново."
                    )
                )
            )

    def _build_incoming(self, form: QFormLayout) -> None:
        """The account each reason of a mədaxil credits (D91)."""
        incoming = QLabel(tr("Оприходование"))
        incoming.setFont(fonts().heading)
        form.addRow(incoming)
        self.incoming_roles = {}
        for key, (name, role) in INCOMING_REASONS.items():
            other_income = key in ("surplus", "gift")  # else FX_GAIN's account
            empty = tr("— прочие доходы —") if other_income else tr("— не указан —")
            self.incoming_roles[role] = self._account_list(role, empty)
            form.addRow(tr(name), self.incoming_roles[role])
        form.addRow(self._hint(N_("Оприходование: Дт счёт товара / Кт счёт причины.")))

    def _account_list(self, role: str, empty: str, width: int = 28) -> QComboBox:
        current = self.s.ledger.account_role(self.s.company_id, role)
        return self._account_combo(empty, current, width)

    def _account_combo(self, empty: str, current: int | None, width: int = 28) -> QComboBox:
        combo = QComboBox()
        # long account names do not squeeze the labels
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(width)
        combo.addItem(empty, None)
        for account in self.s.catalog.leaf_accounts:
            combo.addItem(account.label, account.id)
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
            roles = {INPUT_VAT: self.input_vat, **self.sale_roles, **self.incoming_roles}
            for role, combo in roles.items():
                if combo.currentData() != self.s.ledger.account_role(self.s.company_id, role):
                    self.s.ledger.set_account_role(self.s.company_id, role, combo.currentData())
            Inventory(self.s.conn, actor=self.s.ledger.actor).set_sale_accounts(
                self.s.company_id,
                {key: combo.currentData() for key, combo in self.sale_accounts.items()},
            )
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Настройки склада"), str(exc))
            return
        self.accept()
