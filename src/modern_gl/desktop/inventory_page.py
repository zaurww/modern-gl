"""Inventory balances and compact dialogs for the first operational workflow."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    SALE_ROLE_NAMES,
    Inventory,
    format_quantity,
)
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    EmptyState,
    PageHeader,
    button,
    money,
    more_button,
    ru_date,
)
from modern_gl.domain.accounts import INPUT_VAT, SALES_VAT
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction
from modern_gl.reporting.inventory import (
    InventoryDocumentSummary,
    ItemDetails,
    StockBalance,
    code_label,
    has_units,
    item_details,
    list_inventory_documents,
    stock_account_choices,
    stock_balances,
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


@dataclass(frozen=True)
class StockGroup:
    """A group header in the stock list: the group and the value of what it holds."""

    name: str
    amount: int


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


class InventoryPage(QWidget):
    key = ("inventory",)
    open_inventory_document = Signal(int)
    new_inventory_document = Signal(str)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(14)
        self.header = PageHeader(tr("Склад"), "")
        add_item = button(tr("+ Товар"), "flat")
        add_item.clicked.connect(self.add_item)
        self.header.add_action(add_item)
        self.header.add_action(  # what is set up once, rarely
            more_button(
                lambda: [
                    (tr("+ Единица"), self.add_unit),
                    (tr("+ Склад"), self.add_warehouse),
                    (tr("+ Вид расходов"), self.add_landed_cost_type),
                    (tr("Настройки склада…"), self.settings),
                ]
            )
        )
        root.addWidget(self.header)

        self._build_operations(root)
        self._build_stock(root)
        self._build_documents(root)
        self.refresh()

    def _build_operations(self, root: QVBoxLayout) -> None:
        operations = QHBoxLayout()
        operations.setSpacing(6)
        for title, operation, kind in (
            ("Начальные остатки", "opening", "flat"),
            ("Списание", "issue", "primary"),
            ("Перемещение", "transfer", "flat"),
            ("Дополнительные расходы", "landed_cost", "flat"),
        ):
            control = button(tr(title), kind)
            control.clicked.connect(lambda _=False, op=operation: self.operation(op))
            operations.addWidget(control)
        operations.addStretch(1)
        root.addLayout(operations)

    def _build_stock(self, root: QVBoxLayout) -> None:
        self.model = ReportModel()
        self.table = QTableView()
        self.table.setObjectName("list")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.doubleClicked.connect(  # the item: its name, group, unit, account
            lambda index: self.edit_item(index.data(Qt.ItemDataRole.UserRole))
        )
        self.empty = EmptyState(
            "□",
            tr("На складе пока пусто"),
            tr("Добавьте товар и склад, затем введите покупку в «Покупках и продажах»."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 2)

    def _build_documents(self, root: QVBoxLayout) -> None:
        recent = QHBoxLayout()
        recent_title = QLabel(tr("Последние складские документы"))
        recent_title.setFont(fonts().heading)
        recent.addWidget(recent_title, 1)
        remove = button(tr("Удалить документ"), "danger")
        remove.clicked.connect(self.delete_document)
        recent.addWidget(remove)
        root.addLayout(recent)
        self.documents_model = ReportModel()
        self.documents = QTableView()
        self.documents.setObjectName("list")
        self.documents.setModel(self.documents_model)
        self.documents.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.documents.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.documents.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.documents.setShowGrid(False)
        self.documents.verticalHeader().hide()
        self.documents.verticalHeader().setDefaultSectionSize(32)
        self.documents.doubleClicked.connect(
            lambda index: self._open_document(index.data(Qt.ItemDataRole.UserRole))
        )
        root.addWidget(self.documents, 1)
        hint = QLabel(
            tr(
                "Количество и стоимость рассчитаны по проведённым складским документам; "
                "проводки создаются автоматически."
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        root.addWidget(hint)

    def title(self) -> str:
        return tr("Склад")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self) -> None:
        balances = stock_balances(self.s.conn, self.s.company_id)
        rows: list[StockBalance | StockGroup] = []
        if any(b.group for b in balances):  # each group under its header with its value
            for group, members in groupby(balances, key=lambda b: b.group):
                members = list(members)
                rows.append(StockGroup(group or tr("Без группы"), sum(b.amount for b in members)))
                rows.extend(members)
        else:
            rows = list(balances)

        def average(row) -> int:
            if isinstance(row, StockGroup) or not row.quantity:
                return 0
            numerator = row.amount * QUANTITY_FACTOR
            quotient, remainder = divmod(numerator, row.quantity)
            return quotient + int(remainder * 2 >= row.quantity)

        self.model.set(
            [
                Column(
                    tr("Товар"),
                    lambda row: (
                        row.name
                        if isinstance(row, StockGroup)
                        else code_label(row.item_code, row.item_name)
                    ),
                    width=260,
                ),
                Column(tr("Склад"), lambda row: getattr(row, "warehouse_name", ""), width=220),
                Column(
                    tr("Количество"),
                    lambda row: (
                        ""
                        if isinstance(row, StockGroup)
                        else format_quantity(row.quantity, row.precision)
                    ),
                    width=130,
                ),
                Column(tr("Ед."), lambda row: getattr(row, "unit_code", ""), width=80),
                Column(tr("Средняя цена"), average, money=True, width=130),
                Column(tr("Стоимость"), lambda row: row.amount, money=True, width=150),
            ],
            rows,
            emphasis=lambda row: isinstance(row, StockGroup),
            section=lambda row: isinstance(row, StockGroup),
        )
        header = self.table.horizontalHeader()
        for index, column in enumerate(self.model.columns):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            if column.width:
                self.table.setColumnWidth(index, column.width)
        header.setStretchLastSection(True)
        self.stack.setCurrentWidget(self.table if rows else self.empty)
        self.header.subtitle.setText(
            tr(
                "{items} позиций · {amount}",
                items=len(balances),
                amount=money(sum(r.amount for r in balances), False),
            )
        )
        self._show_documents()

    def _show_documents(self) -> None:
        """The warehouse documents."""
        documents = list_inventory_documents(self.s.conn, self.s.company_id)
        self.documents_model.set(
            [
                Column(tr("Дата"), lambda row: ru_date(row.doc_date), width=110),
                Column(tr("№"), lambda row: row.number, width=65),
                Column(
                    tr("Операция"),
                    lambda row: self._document_type(row.doc_type),
                    width=170,
                ),
                Column(
                    tr("Статус"),
                    lambda row: tr("Проведён") if row.status == "posted" else tr("Черновик"),
                    width=105,
                ),
                Column(tr("Статья расходов"), lambda row: row.cost_type_name, width=160),
                Column(tr("Комментарий"), lambda row: row.memo, width=260),
                Column(tr("Сумма"), lambda row: row.amount, money=True, width=130),
            ],
            documents,
        )
        docs_header = self.documents.horizontalHeader()
        for index, column in enumerate(self.documents_model.columns):
            docs_header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            if column.width:
                self.documents.setColumnWidth(index, column.width)
        docs_header.setStretchLastSection(True)

    def add_unit(self) -> None:
        code, ok = QInputDialog.getText(self, tr("Новая единица"), tr("Краткое обозначение:"))
        if not ok or not code.strip():
            return
        name, ok = QInputDialog.getText(self, tr("Новая единица"), tr("Полное название:"))
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_unit(self.s.company_id, code, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Единица «{name}» добавлена", name=name.strip()))

    def add_item(self) -> None:
        if not has_units(self.s.conn, self.s.company_id):
            self.s.notify(tr("Сначала добавьте единицу измерения"))
            return
        dialog = ItemDialog(self.s, self.inventory, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.s.catalog.reload()
            self.s.notify(tr("Товар добавлен"))
            self.refresh()

    def edit_item(self, row) -> None:
        if not isinstance(row, StockBalance):
            return
        self.s.catalog.reload()
        if open_item(self.s, self.inventory, row.item_value_id, self):
            self.refresh()

    def add_warehouse(self) -> None:
        name, ok = QInputDialog.getText(self, tr("Новый склад"), tr("Название склада:"))
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_warehouse(self.s.company_id, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.catalog.reload()
        self.s.notify(tr("Склад «{name}» добавлен", name=name.strip()))
        self.refresh()

    def add_landed_cost_type(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr("Новый вид расходов"),
            tr("Название (например, доставка или таможня):"),
        )
        if not ok or not name.strip():
            return
        try:
            self.inventory.add_landed_cost_type(self.s.company_id, name)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Вид расходов «{name}» добавлен", name=name.strip()))

    def settings(self) -> None:
        if InventorySettingsDialog(self.s, self).exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Настройки склада сохранены"))

    def operation(self, operation: str) -> None:
        self.new_inventory_document.emit(operation)

    @staticmethod
    def _document_type(doc_type: str) -> str:
        return {
            "opening": tr("Начальные остатки"),
            "receipt": tr("Покупка"),
            "issue": tr("Списание"),
            "sale": tr("Продажа"),
            "transfer": tr("Перемещение"),
            "landed_cost": tr("Дополнительные расходы"),
        }.get(doc_type, doc_type)

    def _selected_document(self) -> InventoryDocumentSummary | None:
        index = self.documents.currentIndex()
        return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None

    def _open_document(self, row: InventoryDocumentSummary | None) -> None:
        if row is not None:
            self.open_inventory_document.emit(row.id)

    def delete_document(self) -> None:
        row = self._selected_document()
        if row is None:
            self.s.notify(tr("Выберите складской документ"))
            return
        answer = QMessageBox.question(
            self,
            tr("Удалить складской документ"),
            tr("Удалить складской документ №{n}?", n=row.number),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.inventory.delete_document(self.s.company_id, row.id)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Складской документ №{n} удалён", n=row.number))
        self.refresh()
