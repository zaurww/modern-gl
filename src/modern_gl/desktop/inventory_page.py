"""Inventory balances and compact dialogs for the first operational workflow."""

from __future__ import annotations

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
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    InventoryDocumentSummary,
    code_label,
    has_units,
    list_inventory_documents,
    stock_account_choices,
    stock_balances,
    unit_choices,
)


class ItemDialog(QDialog):
    def __init__(self, session: Session, inventory: Inventory, parent=None, name: str = "") -> None:
        super().__init__(parent)
        self.s, self.inventory = session, inventory
        self.item_id: int | None = None
        self.setWindowTitle(tr("Новый товар"))
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.code = QLineEdit()
        self.units = QComboBox()
        for unit in unit_choices(session.conn, session.company_id):
            self.units.addItem(unit.label, unit.id)
        self.accounts = QComboBox()
        for account in stock_account_choices(session.conn, session.company_id):
            self.accounts.addItem(account.label, account.id)
        form.addRow(tr("Наименование"), self.name)
        form.addRow(tr("Артикул"), self.code)
        form.addRow(tr("Единица измерения"), self.units)
        form.addRow(tr("Счёт запасов"), self.accounts)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        if not self.name.text().strip() or self.units.currentData() is None:
            QMessageBox.warning(self, tr("Новый товар"), tr("Заполните название и единицу"))
            return
        if self.accounts.currentData() is None:
            QMessageBox.warning(
                self,
                tr("Новый товар"),
                tr("В плане счетов нет счёта с субконто Товар и Склад"),
            )
            return
        try:
            self.item_id = self.inventory.add_item(
                self.s.company_id,
                self.name.text(),
                int(self.units.currentData()),
                int(self.accounts.currentData()),
                self.code.text(),
            )
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Новый товар"), str(exc))
            return
        self.accept()


class InventorySettingsDialog(QDialog):
    """Accounts the warehouse posts to by itself: chosen here, not found by a code."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Настройки склада"))
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.input_vat = QComboBox()
        self.input_vat.addItem(tr("— не указан —"), None)
        for account in session.catalog.leaf_accounts:
            self.input_vat.addItem(account.label, account.id)
        current = session.ledger.account_role(session.company_id, INPUT_VAT)
        self.input_vat.setCurrentIndex(max(self.input_vat.findData(current), 0))
        form.addRow(tr("Счёт НДС к возмещению"), self.input_vat)
        hint = QLabel(tr("Поступление с НДС: Дт этот счёт [поставщик] / Кт счёт расчётов."))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        try:
            self.s.ledger.set_account_role(
                self.s.company_id, INPUT_VAT, self.input_vat.currentData()
            )
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

        operations = QHBoxLayout()
        operations.setSpacing(6)
        for title, operation, kind in (
            ("Начальные остатки", "opening", "flat"),
            ("Поступление", "receipt", "primary"),
            ("Списание", "issue", "flat"),
            ("Перемещение", "transfer", "flat"),
            ("Расходы по партии", "landed_cost", "flat"),
        ):
            control = button(tr(title), kind)
            control.clicked.connect(lambda _=False, op=operation: self.operation(op))
            operations.addWidget(control)
        operations.addStretch(1)
        root.addLayout(operations)

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setObjectName("list")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.empty = EmptyState(
            "□",
            tr("На складе пока пусто"),
            tr("Добавьте товар и склад, затем введите поступление."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 2)

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
        self.refresh()

    def title(self) -> str:
        return tr("Склад")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self) -> None:
        rows = stock_balances(self.s.conn, self.s.company_id)

        def average(row) -> int:
            if not row.quantity:
                return 0
            numerator = row.amount * QUANTITY_FACTOR
            quotient, remainder = divmod(numerator, row.quantity)
            return quotient + int(remainder * 2 >= row.quantity)

        self.model.set(
            [
                Column(
                    tr("Товар"), lambda row: code_label(row.item_code, row.item_name), width=260
                ),
                Column(tr("Склад"), lambda row: row.warehouse_name, width=220),
                Column(
                    tr("Количество"),
                    lambda row: format_quantity(row.quantity, row.precision),
                    width=130,
                ),
                Column(tr("Ед."), lambda row: row.unit_code, width=80),
                Column(tr("Средняя цена"), average, money=True, width=130),
                Column(tr("Стоимость"), lambda row: row.amount, money=True, width=150),
            ],
            rows,
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
                items=len(rows),
                amount=money(sum(r.amount for r in rows), False),
            )
        )
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
            "receipt": tr("Поступление"),
            "issue": tr("Списание"),
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
