"""Inventory balances and compact dialogs for the first operational workflow."""

from __future__ import annotations

from datetime import date

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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import (
    QUANTITY_FACTOR,
    Inventory,
    IssueLine,
    ReceiptLine,
    TransferLine,
    format_quantity,
)
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, date_edit, money, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import stock_balances


def _label(code: str | None, name: str) -> str:
    return f"{code}  {name}" if code else name


class AccountPicker(QWidget):
    """An account and the subconto values required by that account."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.account = QComboBox()
        for account in session.catalog.leaf_accounts:
            self.account.addItem(account.label, account.id)
        layout.addWidget(self.account)
        self.dimensions: list[QComboBox] = []
        for _ in range(3):
            combo = QComboBox()
            combo.hide()
            layout.addWidget(combo)
            self.dimensions.append(combo)
        self.account.currentIndexChanged.connect(self._account_changed)
        self._account_changed()

    def select_code(self, code: str) -> None:
        account = self.s.catalog.by_code.get(code)
        if account is not None:
            index = self.account.findData(account.id)
            if index >= 0:
                self.account.setCurrentIndex(index)

    def account_id(self) -> int:
        return int(self.account.currentData())

    def subconto(self) -> list[int | None]:
        account = self.s.catalog.accounts[self.account_id()]
        result: list[int | None] = []
        for kind_id, combo in zip(account.sc_kinds, self.dimensions, strict=True):
            if kind_id is not None and combo.currentData() is None:
                raise LedgerError(
                    tr("Заполните субконто «{kind}»", kind=self.s.catalog.kinds[kind_id])
                )
            result.append(int(combo.currentData()) if kind_id is not None else None)
        while result and result[-1] is None:
            result.pop()
        return result

    def _account_changed(self) -> None:
        account_id = self.account.currentData()
        if account_id is None:
            return
        account = self.s.catalog.accounts[int(account_id)]
        for kind_id, combo in zip(account.sc_kinds, self.dimensions, strict=True):
            combo.clear()
            if kind_id is None:
                combo.hide()
                continue
            combo.setPlaceholderText(self.s.catalog.kinds[kind_id])
            for value in self.s.catalog.values(kind_id):
                combo.addItem(value.name, value.id)
            if combo.count():
                combo.setCurrentIndex(0)
            combo.show()


class ItemDialog(QDialog):
    def __init__(self, session: Session, inventory: Inventory, parent=None) -> None:
        super().__init__(parent)
        self.s, self.inventory = session, inventory
        self.setWindowTitle(tr("Новый товар"))
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.code = QLineEdit()
        self.units = QComboBox()
        for row in session.conn.execute(
            "SELECT id, code, name FROM inventory_units WHERE company_id = ? AND active = 1 "
            "ORDER BY name",
            (session.company_id,),
        ):
            self.units.addItem(_label(row["code"], row["name"]), row["id"])
        self.accounts = QComboBox()
        for row in session.conn.execute(
            """
            SELECT a.id, a.code, a.name FROM accounts a
            WHERE a.company_id = ? AND a.active = 1 AND a.is_group = 0
              AND EXISTS (
                SELECT 1 FROM subconto_kinds k WHERE k.company_id = a.company_id
                  AND k.code = 'item' AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
              )
              AND EXISTS (
                SELECT 1 FROM subconto_kinds k WHERE k.company_id = a.company_id
                  AND k.code = 'warehouse'
                  AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
              )
            ORDER BY a.code IS NULL, a.code, a.name
            """,
            (session.company_id,),
        ):
            self.accounts.addItem(_label(row["code"], row["name"]), row["id"])
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
            self.inventory.add_item(
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


class OperationDialog(QDialog):
    def __init__(self, session: Session, inventory: Inventory, operation: str, parent=None) -> None:
        super().__init__(parent)
        self.s, self.inventory, self.operation = session, inventory, operation
        titles = {
            "opening": tr("Начальные остатки"),
            "receipt": tr("Поступление"),
            "issue": tr("Списание"),
            "transfer": tr("Перемещение"),
            "landed_cost": tr("Дополнительные расходы"),
        }
        self.setWindowTitle(titles[operation])
        self.setMinimumWidth(470)
        self.form = QFormLayout(self)
        self.when = date_edit(session.working_date, self)
        self.form.addRow(tr("Дата"), self.when)
        self.item = QComboBox()
        self.warehouse = QComboBox()
        self.to_warehouse = QComboBox()
        self.receipt_lines = QListWidget()
        self.receipt_lines.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.receipt_lines.setMinimumHeight(130)
        self.allocation_method = QComboBox()
        self.allocation_method.addItem(tr("По стоимости"), "value")
        self.allocation_method.addItem(tr("По количеству"), "quantity")
        self.cost_type = QComboBox()
        self.cost_type.addItem(tr("Без статьи"), None)
        for row in session.conn.execute(
            "SELECT id, code, name FROM landed_cost_types "
            "WHERE company_id = ? AND active = 1 ORDER BY name",
            (session.company_id,),
        ):
            self.cost_type.addItem(_label(row["code"], row["name"]), row["id"])
        self.quantity = QLineEdit()
        self.quantity.setPlaceholderText("0")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.offset = AccountPicker(session)
        self.memo = QLineEdit()

        for row in session.conn.execute(
            """
            SELECT i.id, v.code, v.name FROM inventory_items i
            JOIN subconto_values v ON v.id = i.subconto_value_id
            WHERE i.company_id = ? AND v.active = 1 ORDER BY v.name
            """,
            (session.company_id,),
        ):
            self.item.addItem(_label(row["code"], row["name"]), row["id"])
        for row in session.conn.execute(
            """
            SELECT w.id, v.code, v.name FROM warehouses w
            JOIN subconto_values v ON v.id = w.subconto_value_id
            WHERE w.company_id = ? AND v.active = 1 ORDER BY v.name
            """,
            (session.company_id,),
        ):
            label = _label(row["code"], row["name"])
            self.warehouse.addItem(label, row["id"])
            self.to_warehouse.addItem(label, row["id"])

        if operation == "landed_cost":
            for row in session.conn.execute(
                """
                SELECT l.id, d.doc_date, d.number, v.name, l.quantity, l.amount, u.precision
                FROM inventory_lines l
                JOIN inventory_documents d ON d.id = l.document_id
                JOIN inventory_items i ON i.id = l.item_id
                JOIN subconto_values v ON v.id = i.subconto_value_id
                JOIN inventory_units u ON u.id = i.unit_id
                WHERE l.company_id = ? AND d.status = 'posted'
                  AND d.doc_type IN ('opening', 'receipt')
                ORDER BY d.doc_date DESC, d.id DESC, l.line_no
                """,
                (session.company_id,),
            ):
                entry = QListWidgetItem(
                    tr(
                        "{date} №{number} · {item} · {quantity} · {amount}",
                        date=row["doc_date"],
                        number=row["number"],
                        item=row["name"],
                        quantity=format_quantity(row["quantity"], row["precision"]),
                        amount=money(row["amount"], blank_zero=False),
                    )
                )
                entry.setData(Qt.ItemDataRole.UserRole, row["id"])
                self.receipt_lines.addItem(entry)
            if self.receipt_lines.count():
                self.receipt_lines.item(0).setSelected(True)
            self.form.addRow(tr("Статья расходов"), self.cost_type)
            self.form.addRow(tr("Поступления"), self.receipt_lines)
            self.form.addRow(tr("Способ распределения"), self.allocation_method)
            self.form.addRow(tr("Сумма расходов"), self.amount)
            self.form.addRow(tr("Счёт расчётов"), self.offset)
            self.offset.select_code("60")
        else:
            self.form.addRow(tr("Товар"), self.item)
            self.form.addRow(tr("Склад"), self.warehouse)
            if operation == "transfer":
                self.form.addRow(tr("Склад-получатель"), self.to_warehouse)
            self.form.addRow(tr("Количество"), self.quantity)
            if operation in {"opening", "receipt"}:
                self.form.addRow(tr("Сумма"), self.amount)
                self.form.addRow(tr("Счёт расчётов"), self.offset)
                self.offset.select_code("60")
            elif operation == "issue":
                self.form.addRow(tr("Счёт затрат"), self.offset)
                self.offset.select_code("46")
        self.form.addRow(tr("Комментарий"), self.memo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)

    def _save(self) -> None:
        try:
            self._post()
        except (LedgerError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.accept()

    def _post(self) -> None:
        company_id = self.s.company_id
        doc_date: date = self.when.date().toPython()
        memo = self.memo.text().strip()
        if self.operation == "landed_cost":
            receipt_line_ids = [
                int(item.data(Qt.ItemDataRole.UserRole))
                for item in self.receipt_lines.selectedItems()
            ]
            if not receipt_line_ids:
                raise ValueError(tr("Нет проведённых поступлений"))
            self.inventory.post_landed_cost(
                company_id,
                doc_date,
                receipt_line_ids,
                self.amount.text(),
                self.offset.account_id(),
                self.offset.subconto(),
                memo,
                method=str(self.allocation_method.currentData()),
                cost_type_id=(
                    int(self.cost_type.currentData()) if self.cost_type.currentData() else None
                ),
            )
            return
        if self.item.currentData() is None or self.warehouse.currentData() is None:
            raise ValueError(tr("Сначала добавьте товар и склад"))
        item_id, warehouse_id = int(self.item.currentData()), int(self.warehouse.currentData())
        if self.operation in {"opening", "receipt"}:
            self.inventory.post_receipt(
                company_id,
                doc_date,
                [ReceiptLine(item_id, warehouse_id, self.quantity.text(), self.amount.text())],
                self.offset.account_id(),
                self.offset.subconto(),
                memo,
                opening=self.operation == "opening",
            )
        elif self.operation == "issue":
            self.inventory.post_issue(
                company_id,
                doc_date,
                [
                    IssueLine(
                        item_id,
                        warehouse_id,
                        self.quantity.text(),
                        self.offset.account_id(),
                        self.offset.subconto(),
                    )
                ],
                memo,
            )
        else:
            self.inventory.post_transfer(
                company_id,
                doc_date,
                [
                    TransferLine(
                        item_id,
                        warehouse_id,
                        int(self.to_warehouse.currentData()),
                        self.quantity.text(),
                    )
                ],
                memo,
            )


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
        for title, action in (
            ("+ Единица", self.add_unit),
            ("+ Товар", self.add_item),
            ("+ Склад", self.add_warehouse),
            ("+ Вид расходов", self.add_landed_cost_type),
        ):
            control = button(tr(title), "flat")
            control.clicked.connect(action)
            self.header.add_action(control)
        root.addWidget(self.header)

        operations = QHBoxLayout()
        operations.setSpacing(6)
        for title, operation, kind in (
            ("Начальные остатки", "opening", "flat"),
            ("Поступление", "receipt", "primary"),
            ("Списание", "issue", "flat"),
            ("Перемещение", "transfer", "flat"),
            ("Доп. расходы", "landed_cost", "flat"),
        ):
            control = button(tr(title), kind)
            control.clicked.connect(lambda _=False, op=operation: self.operation(op))
            operations.addWidget(control)
        operations.addStretch(1)
        root.addLayout(operations)

        self.model = ReportModel()
        self.table = QTableView()
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
                Column(tr("Товар"), lambda row: _label(row.item_code, row.item_name), width=260),
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
        documents = self.s.conn.execute(
            """
            SELECT d.id, d.number, d.doc_date, d.doc_type, d.memo, d.status,
                   d.gl_document_id,
                   ct.name AS cost_type_name,
                   COALESCE(SUM(l.amount), 0) AS amount
            FROM inventory_documents d
            LEFT JOIN inventory_lines l ON l.document_id = d.id
            LEFT JOIN landed_cost_types ct ON ct.id = d.landed_cost_type_id
            WHERE d.company_id = ?
            GROUP BY d.id
            ORDER BY d.doc_date DESC, d.id DESC
            LIMIT 100
            """,
            (self.s.company_id,),
        ).fetchall()
        self.documents_model.set(
            [
                Column(tr("Дата"), lambda row: ru_date(row["doc_date"]), width=110),
                Column(tr("№"), lambda row: row["number"], width=65),
                Column(
                    tr("Операция"),
                    lambda row: self._document_type(row["doc_type"]),
                    width=170,
                ),
                Column(
                    tr("Статус"),
                    lambda row: tr("Проведён") if row["status"] == "posted" else tr("Черновик"),
                    width=105,
                ),
                Column(tr("Статья расходов"), lambda row: row["cost_type_name"], width=160),
                Column(tr("Комментарий"), lambda row: row["memo"], width=260),
                Column(tr("Сумма"), lambda row: row["amount"], money=True, width=130),
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
        units = self.s.conn.execute(
            "SELECT 1 FROM inventory_units WHERE company_id = ? LIMIT 1", (self.s.company_id,)
        ).fetchone()
        if units is None:
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

    def operation(self, operation: str) -> None:
        if operation != "landed_cost":
            self.new_inventory_document.emit(operation)
            return
        dialog = OperationDialog(self.s, self.inventory, operation, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Складской документ проведён"))
            self.refresh()

    @staticmethod
    def _document_type(doc_type: str) -> str:
        return {
            "opening": tr("Начальные остатки"),
            "receipt": tr("Поступление"),
            "issue": tr("Списание"),
            "transfer": tr("Перемещение"),
            "landed_cost": tr("Дополнительные расходы"),
        }.get(doc_type, doc_type)

    def _selected_document(self):
        index = self.documents.currentIndex()
        return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None

    def _open_document(self, row) -> None:
        if row is not None:
            self.open_inventory_document.emit(row["id"])

    def delete_document(self) -> None:
        row = self._selected_document()
        if row is None:
            self.s.notify(tr("Выберите складской документ"))
            return
        answer = QMessageBox.question(
            self,
            tr("Удалить складской документ"),
            tr("Удалить складской документ №{n}?", n=row["number"]),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.inventory.delete_document(self.s.company_id, row["id"])
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Складской документ №{n} удалён", n=row["number"]))
        self.refresh()
