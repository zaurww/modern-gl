"""The page of a warehouse document: header, lines, totals; save, post, unpost."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

from PySide6.QtCore import (
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
    Inventory,
    InventoryDocumentData,
    vat_of,
)
from modern_gl.desktop.cell_editing import edit_again, edit_next, resolve_choice
from modern_gl.desktop.inventory_document_page.columns import (
    DOCUMENT_TYPES,
    EXPENSE,
    HINT,
    ITEM,
    MEMO,
    QUANTITY,
    VAT_DOCUMENTS,
    VAT_RATES,
    WAREHOUSE,
    InventoryGridRow,
    InventoryPaste,
)
from modern_gl.desktop.inventory_document_page.lines_model import (
    InventoryLinesModel,
    by_sale_kinds,
    sale_kinds,
)
from modern_gl.desktop.inventory_document_page.lines_table import (
    InventoryLinesDelegate,
    InventoryLinesTable,
    NewNamesDialog,
)
from modern_gl.desktop.inventory_page import ItemDialog
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.postings import plain_number
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    button,
    date_edit,
    edited_date,
    enter_goes_on,
    money,
    to_qdate,
)
from modern_gl.domain.accounts import INPUT_VAT, OUTPUT_VAT
from modern_gl.domain.currency import format_unit_rate, parse_rate, unit_rate
from modern_gl.domain.dates import earlier_months, month_name
from modern_gl.domain.eqaime import status_group, status_label
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.invoice import CUSTOMS, EQAIME
from modern_gl.i18n import fold, tr
from modern_gl.reporting.eqaime_reconciliation import portal_status
from modern_gl.reporting.inventory import (
    unit_choices,
)


class InventoryDocumentPage(QWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)

    def __init__(
        self,
        session: Session,
        document_id: int | None = None,
        doc_type: str = "receipt",
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.doc: InventoryDocumentData | None = None
        self.doc_type = doc_type
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)

        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        self.memo.setPlaceholderText(tr("Комментарий складского документа"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        meta = QHBoxLayout()
        date_caption = QLabel(tr("Дата"))
        date_caption.setObjectName("secondary")
        meta.addWidget(date_caption)
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addSpacing(12)
        type_caption = QLabel(tr("Операция"))
        type_caption.setObjectName("secondary")
        meta.addWidget(type_caption)
        self.type_label = QLabel(tr(DOCUMENT_TYPES.get(doc_type, doc_type)))
        self.type_label.setFont(fonts().heading)
        meta.addWidget(self.type_label)
        meta.addSpacing(12)
        self.vat_caption = QLabel(tr("НДС"))
        self.vat_caption.setObjectName("secondary")
        meta.addWidget(self.vat_caption)
        self.vat_rate = PickBox()
        self.vat_rate.setFixedWidth(110)
        for rate, label in VAT_RATES:
            self.vat_rate.addItem(tr(label), rate)
        meta.addWidget(self.vat_rate)
        meta.addSpacing(12)
        # the basis of a receipt: an e-qaimə, or a customs declaration for imported goods
        self.basis = PickBox()
        self.basis.setFixedWidth(120)
        self.basis.addItem(tr("E-qaimə"), EQAIME)
        self.basis.addItem(tr("Декларация"), CUSTOMS)
        self.basis.setCurrentIndex(0)
        self.basis.setToolTip(tr("Основание: e-qaimə или таможенная декларация (импорт)"))
        meta.addWidget(self.basis)
        self.invoice_caption = QLabel(tr("E-qaimə"))  # a sale's basis is always an e-qaimə
        self.invoice_caption.setObjectName("secondary")
        meta.addWidget(self.invoice_caption)
        self.invoice = QLineEdit()
        self.invoice.setFixedWidth(170)
        self.invoice.setPlaceholderText(tr("номер"))
        meta.addWidget(self.invoice)
        # what the portal said of it when last read: awaiting approval, cancelled… (D53)
        self.portal_status = Chip()
        self.portal_status.hide()
        meta.addWidget(self.portal_status)
        meta.addSpacing(12)
        # services of an earlier month whose e-qaimə came later: accrued there (D65)
        self.expense_caption = QLabel(tr("Расход за"))
        self.expense_caption.setObjectName("secondary")
        meta.addWidget(self.expense_caption)
        self.expense_month = PickBox()
        self.expense_month.setFixedWidth(150)
        self.expense_month.setToolTip(
            tr(
                "Месяц расхода по услугам, если e-qaimə пришла позже: расход начисляется "
                "последним днём этого месяца (Дт затрат / Кт 76H), долг поставщику и НДС — "
                "датой e-qaimə"
            )
        )
        meta.addWidget(self.expense_month)
        meta.addSpacing(12)
        self.currency_caption = QLabel(tr("Валюта"))
        self.currency_caption.setObjectName("secondary")
        meta.addWidget(self.currency_caption)
        self.currency = PickBox()
        self.currency.setFixedWidth(80)
        self.currency.addItem("AZN", None)
        for currency in session.catalog.active_currencies:
            self.currency.addItem(currency.code, currency.id)
        self.currency.setCurrentIndex(0)
        meta.addWidget(self.currency)
        self.rate_caption = QLabel(tr("Курс"))
        self.rate_caption.setObjectName("secondary")
        meta.addWidget(self.rate_caption)
        self.rate = QLineEdit()
        self.rate.setFixedWidth(90)
        self.rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.rate.setPlaceholderText(tr("курс"))
        self.rate.setToolTip(tr("Курс на дату документа; можно исправить (например, курс таможни)"))
        meta.addWidget(self.rate)
        self.rate_typed = False  # typed by hand: a new date no longer changes it
        meta.addStretch(1)
        root.addLayout(meta)

        # a new receipt (sale) has VAT when the company has an account to post its VAT to
        vat_role = OUTPUT_VAT if doc_type == "sale" else INPUT_VAT
        has_vat_account = session.ledger.account_role(session.company_id, vat_role) is not None
        self._show_vat_rate(STANDARD_VAT_RATE if has_vat_account else None)
        self.model = InventoryLinesModel(session, doc_type, vat_rate=self._chosen_vat_rate())
        self.delegate = InventoryLinesDelegate(self)
        self.table = InventoryLinesTable(self.model, self.delegate)
        self.expense_columns = self._expense_columns()  # shown for these
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        summary = QHBoxLayout()
        self.hint = QLabel(tr(HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        summary.addWidget(self.hint, 1)
        summary.addSpacing(24)
        self.currency_total = QLabel()
        self.currency_total.setObjectName("secondary")
        summary.addWidget(self.currency_total)
        summary.addSpacing(16)
        self.vat_total_caption = QLabel(tr("НДС"))
        self.vat_total_caption.setObjectName("secondary")
        summary.addWidget(self.vat_total_caption)
        self.vat_total = QLabel()
        self.vat_total.setMinimumWidth(90)
        self.vat_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.vat_total)
        summary.addSpacing(16)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
        summary.addWidget(total_caption)
        self.total = QLabel()
        self.total.setMinimumWidth(130)
        self.total.setFont(fonts().total)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.total)
        root.addLayout(summary)

        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_accrual = button(tr("Начисление"), "flat")
        self.btn_accrual.setToolTip(tr("Проводки начисления расхода в месяце услуги"))
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_accrual)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        self.btn_accrual.clicked.connect(self._open_accrual)
        self._connect_delegate()
        self.model.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.vat_rate.activated.connect(self._vat_rate_changed)
        self.basis.activated.connect(self._changed)
        self.invoice.textEdited.connect(self._changed)
        self.expense_month.activated.connect(self._changed)
        self.currency.activated.connect(self._currency_changed)
        self.rate.textEdited.connect(self._rate_edited)
        self.date.dateChanged.connect(self._date_changed)
        self.date.dateChanged.connect(self._expense_months_changed)
        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self._grid_shortcut("Ins", self._insert_row, while_editing=True)
        self._grid_shortcut("F9", self._duplicate_row, while_editing=True)
        self._grid_shortcut("Del", self._remove_row)
        self._grid_shortcut("Ctrl+V", self.paste)  # inside a cell editor: its own paste
        self._grid_shortcut("Ctrl+C", self.copy)

        if document_id is None:
            self._set_new()
        else:
            self.load(document_id)

    @property
    def document_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("inventory_doc", self.document_id) if self.doc else ("new_inventory", id(self))

    def title(self) -> str:
        operation = tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type))
        title = (
            f"{operation} №{self.doc.number}" if self.doc else tr("Новое: {type}", type=operation)
        )
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.table.setFocus()

    def keyPressEvent(self, event) -> None:
        """Enter in the comment, date, VAT, basis, currency or rate goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _shortcut(self, keys: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.activated.connect(callback)

    def _grid_shortcut(self, keys: str, callback, *, while_editing: bool = False) -> None:
        shortcut = QShortcut(QKeySequence(keys), self.table)
        shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
            if while_editing
            else Qt.ShortcutContext.WidgetShortcut
        )
        shortcut.activated.connect(callback)

    def _insert_row(self) -> None:
        if self.model.read_only:
            return
        self._finish_editing()
        current = self.table.currentIndex()
        at = current.row() + 1 if current.isValid() else None
        row = self.model.insert_row(at)
        self.table.setCurrentIndex(self.model.index(row, 0))

    def _duplicate_row(self) -> None:
        self._finish_editing()
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        row = self.model.duplicate_row(current.row())
        self.table.setCurrentIndex(self.model.index(row, 0))

    def _remove_row(self) -> None:
        self._finish_editing()
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self.model.remove_row(current.row())

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    # ---- clipboard -----------------------------------------------------------------

    def _shown(self, column: int) -> bool:
        return not self.table.isColumnHidden(column)

    def paste(self, text: str | None = None) -> None:
        """Lines copied from Excel become lines of the document."""
        if self.model.read_only or self.doc_type == "landed_cost":
            return
        text = QApplication.clipboard().text() if text is None else text
        if not text.strip():
            return
        self.error.hide()
        current = self.table.currentIndex()
        row, column = (current.row(), current.column()) if current.isValid() else (0, 0)
        result = self.model.paste(text, row, column, self._shown)
        problems = list(result.errors)
        if result.unknown:
            try:
                added = self._add_unknown(result)
            except (LedgerError, LookupError) as exc:
                added, problems = False, [*problems, str(exc)]
            if not added:
                problems += [
                    tr("нет в справочнике: {text}", text=text) for _, _, text, _ in result.unknown
                ]
        if problems:
            more = len(problems) - 6
            self.show_error(
                "\n".join(problems[:6]) + (f"\n{tr('и ещё {n}', n=more)}" if more > 0 else "")
            )
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def _add_unknown(self, result: InventoryPaste) -> bool:
        """Add the new items, warehouses and subconto in one go and put them in place."""
        names: dict[tuple[str, int | None, str], None] = {}
        for _, key, text, kind_id in result.unknown:
            group = ITEM if key == ITEM else WAREHOUSE if kind_id is None else "sc"
            names[(group, kind_id, text)] = None
        titles = {ITEM: tr("Товар"), WAREHOUSE: tr("Склад")}
        listing = "\n".join(
            f"{titles[group] if kind_id is None else self.s.catalog.kinds[kind_id]}: {text}"
            for group, kind_id, text in list(names)[:12]
        )
        items = any(group == ITEM for group, _, _ in names)
        dialog = NewNamesDialog(self.s, listing, items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if items and dialog.account.currentData() is None:
            raise LookupError(tr("В плане счетов нет счёта с субконто Товар и Склад"))
        units: dict[str, int] = {}
        created: dict[tuple, int] = {}
        cid = self.s.company_id
        for row, key, text, kind_id in result.unknown:
            if key == ITEM:
                if (ITEM, text) not in created:
                    unit = self._unit(result.units.get(text) or dialog.unit.currentText(), units)
                    account = int(dialog.account.currentData())
                    created[(ITEM, text)] = self.inventory.add_item(cid, text, unit, account)
                value = created[(ITEM, text)]
            elif kind_id is None:  # a warehouse
                if (WAREHOUSE, text) not in created:
                    created[(WAREHOUSE, text)] = self.inventory.add_warehouse(cid, text)
                value = created[(WAREHOUSE, text)]
            else:  # a contract belongs to the counterparty its line has by then
                owner = self.model.owner_at(row, key)
                if (kind_id, text, owner) not in created:
                    value_id = self.s.ledger.add_subconto_value(cid, kind_id, text, owner_id=owner)
                    self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner)
                    created[(kind_id, text, owner)] = value_id
                value = created[(kind_id, text, owner)]
            self.s.catalog.reload()
            self.model.refresh_choices()
            self.model.setData(self.model.index(row, self.model.columns.index(key)), value)
        return True

    def _unit(self, text: str, made: dict[str, int]) -> int:
        """A unit by its code or name; a new one if there is none."""
        text = text.strip()
        choices = [(c.id, c.label) for c in unit_choices(self.s.conn, self.s.company_id)]
        try:
            found = resolve_choice(choices, text) if text else None
        except LookupError:
            found = None
        if found is None:
            if not text:
                raise LookupError(tr("Заполните название и единицу"))
            if fold(text) not in made:
                made[fold(text)] = self.inventory.add_unit(self.s.company_id, text, text)
            found = made[fold(text)]
        return found

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Строки скопированы — их можно вставить в Excel"))

    def _connect_delegate(self) -> None:
        self.delegate.error.connect(self.show_error)
        self.delegate.add_value = self._add_typed_value
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        self.delegate.unknown_value.connect(
            lambda index, kind_id, text: QTimer.singleShot(
                0, lambda: self._create_value(index, kind_id, text)
            )
        )
        self.delegate.unknown_item.connect(
            lambda index, text: QTimer.singleShot(0, lambda: self._create_item(index, text))
        )
        self.delegate.unknown_warehouse.connect(
            lambda index, text, picked: QTimer.singleShot(
                0, lambda: self._create_warehouse(index, text, ask=not picked)
            )
        )

    def _ask_add(self, text: str, directory: str) -> bool:
        answer = QMessageBox.question(
            self,
            tr("Новый элемент справочника"),
            tr("«{text}» нет в справочнике «{kind}». Добавить?", text=text, kind=directory),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        kind = self.s.catalog.kinds[kind_id]
        if not index.isValid():
            return
        if not self._ask_add(text, kind):
            edit_again(self.table, index, text)  # the name, to correct it
            return
        owner = self.model.owner_at(index.row(), self.model.columns[index.column()])
        value_id = self._add_typed_value(kind_id, text, owner)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        edit_next(self.table, index)

    def _add_typed_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        kind = self.s.catalog.kinds[kind_id]
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
        return value_id

    def _create_item(self, index: QPersistentModelIndex, text: str) -> None:
        if not index.isValid():
            return
        if self.doc_type in {"sale", "receipt"}:
            answer = self._service_or_item(text)
            if answer is None:
                edit_again(self.table, index, text)  # the name, to correct it
                return
            if answer == "service":  # what was typed says what the service is
                self._make_service(index.row(), text)
                return
        dialog = ItemDialog(self.s, self.inventory, self, name=text)
        if dialog.units.count() == 0:
            self.show_error(tr("Сначала добавьте единицу измерения"))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.item_id is None:
            edit_again(self.table, index, text)
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), dialog.item_id)
        self.s.notify(tr("Товар добавлен"))
        edit_next(self.table, index)

    def _make_service(self, row: int, text: str) -> None:
        """The line becomes a service with this text; a receipt's goes on to the account the
        service (fixed asset) is charged to."""
        self.model.setData(self.model.index(row, self.model.columns.index(MEMO)), text)
        self.model.setData(self.model.index(row, self.model.columns.index(ITEM)), None)
        self.table.configure_columns()
        key = EXPENSE if self.doc_type == "receipt" else QUANTITY
        index = self.model.index(row, self.model.columns.index(key))
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def _service_or_item(self, text: str) -> str | None:
        """A name the item list does not have: a service (fixed asset), or a new item?"""
        sale = self.doc_type == "sale"
        box = QMessageBox(self)
        box.setWindowTitle(tr(DOCUMENT_TYPES[self.doc_type]))
        box.setText(
            tr("«{text}» нет среди товаров. Это услуга или новый товар?", text=text)
            if sale
            else tr("«{text}» нет среди товаров. Это услуга, ОС или новый товар?", text=text)
        )
        service = box.addButton(
            tr("Услуга") if sale else tr("Услуга, ОС"), QMessageBox.ButtonRole.AcceptRole
        )
        item = box.addButton(tr("Новый товар…"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(service)
        box.exec()
        clicked = box.clickedButton()
        return "service" if clicked is service else "item" if clicked is item else None

    def _create_warehouse(self, index: QPersistentModelIndex, text: str, ask: bool = True) -> None:
        """A warehouse the list lacks; picked as "+ Добавить «…»" it goes in at once."""
        if not index.isValid():
            return
        if ask and not self._ask_add(text, tr("Склад")):
            edit_again(self.table, index, text)
            return
        try:
            warehouse_id = self.inventory.add_warehouse(self.s.company_id, text)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.s.catalog.reload()
        self.model.refresh_choices()
        self.model.setData(self.model.index(index.row(), index.column()), warehouse_id)
        self.s.notify(tr("Склад «{name}» добавлен", name=text))
        edit_next(self.table, index)

    def _show_vat_rate(self, rate: int | None) -> None:
        index = self.vat_rate.findData(rate)
        if index < 0:  # a rate not in the list (set elsewhere): show it as it is
            self.vat_rate.addItem(f"{Decimal(rate or 0).scaleb(-2).normalize():f}%", rate)
            index = self.vat_rate.count() - 1
        self.vat_rate.setCurrentIndex(index)
        with_vat = self.doc_type in VAT_DOCUMENTS
        self.vat_caption.setVisible(with_vat)
        self.vat_rate.setVisible(with_vat)

    def _chosen_vat_rate(self) -> int | None:
        return self.vat_rate.currentData() if self.doc_type in VAT_DOCUMENTS else None

    def _vat_rate_changed(self, *_args) -> None:
        self.model.set_vat_rate(self._chosen_vat_rate())
        self.table.configure_columns()

    # ---- currency -------------------------------------------------------------------

    def _chosen_currency(self) -> int | None:
        return self.currency.currentData() if self.doc_type == "receipt" else None

    def _typed_rate(self) -> Fraction | None:
        try:
            return unit_rate(parse_rate(plain_number(self.rate.text())))
        except (TypeError, ValueError):
            return None

    def _rate_of_the_day(self) -> None:
        """The rate in force on the document's date (unless the rate was typed)."""
        currency_id = self._chosen_currency()
        if currency_id is None or self.rate_typed:
            return
        found = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        self.rate.setText(format_unit_rate(found.per_unit) if found else "")

    def _apply_currency(self) -> None:
        in_currency = self._chosen_currency() is not None
        for widget in (self.rate_caption, self.rate):
            widget.setVisible(in_currency)
        if in_currency:  # an import has no Azerbaijani VAT: it comes with customs
            self._show_vat_rate(None)
            self.model.set_vat_rate(None)
        self.vat_rate.setEnabled(not in_currency and not self.model.read_only)
        self.model.set_currency(self.currency.currentText(), self._typed_rate(), in_currency)
        self.table.configure_columns()

    def _currency_changed(self, *_args) -> None:
        self.rate_typed = False
        self._rate_of_the_day()
        self._apply_currency()

    def _rate_edited(self, *_args) -> None:
        self.rate_typed = True
        self._apply_currency()

    def _date_changed(self, *_args) -> None:
        if self._chosen_currency() is not None and not self.rate_typed:
            self._rate_of_the_day()
            self._apply_currency()

    def _show_totals(self) -> None:
        in_currency = self.model.rate is not None
        self.currency_total.setVisible(in_currency)
        self.currency_total.setText(
            f"{money(self.model.currency_total(), blank_zero=False)} {self.model.currency_code}"
        )
        vat = self.model.vat_total()
        shown = self.doc_type in VAT_DOCUMENTS and self.model.has_vat()
        self.vat_total_caption.setVisible(shown)
        self.vat_total.setVisible(shown)
        self.vat_total.setText(money(vat, blank_zero=False))
        self.total.setText(money(self.model.total() + vat, blank_zero=False))

    def _changed(self, *_args) -> None:
        self._show_totals()
        if self._expense_columns() != self.expense_columns:  # a service line came or went
            self.table.configure_columns()
            self.expense_columns = self._expense_columns()
            self._show_expense_month()
        if not self.model.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def _expense_columns(self) -> tuple[bool, set[int], bool]:
        return self.model.has_expenses(), self.model.expense_positions(), self.model.has_goods()

    def _set_new(self) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        self._apply_mode(False)
        self._show_currency(None, None)
        self._show_basis(EQAIME, "")
        self._fill_expense_months(None)
        self.dirty = False  # showing the defaults is not an edit
        self._show_totals()

    def _show_basis(self, kind: str, number: str) -> None:
        """The e-qaimə / declaration of a receipt, the e-qaimə of a sale; other documents
        have none."""
        self.basis.setCurrentIndex(max(self.basis.findData(kind), 0))
        self.invoice.setText(number)
        self.basis.setVisible(self.doc_type == "receipt")
        self.invoice_caption.setVisible(self.doc_type == "sale")
        self.invoice.setVisible(self.doc_type in VAT_DOCUMENTS)
        self._show_portal_status(kind, number)

    def _show_portal_status(self, kind: str, number: str) -> None:
        """Only what is worth a look: an approved e-qaimə shows nothing."""
        status = None
        if kind == EQAIME and self.doc_type in ("receipt", "sale"):
            status = portal_status(self.s.conn, self.s.company_id, self.doc_type == "sale", number)
        group = status_group(status or "")
        if status is None or group == "turnover":
            self.portal_status.hide()
            return
        self.portal_status.set(status_label(status), "red" if group == "void" else "neutral")
        self.portal_status.setToolTip(tr("Статус на портале при последней загрузке"))
        self.portal_status.show()

    def _invoice(self) -> dict[str, str]:
        """The basis for saving: number and kind (an empty number: none)."""
        number = self.invoice.text().strip()
        if self.doc_type == "sale":
            return {"invoice": number}
        return {"invoice": number, "invoice_kind": self.basis.currentData() if number else ""}

    # ---- the month of the expense (D65) --------------------------------------------

    def _fill_expense_months(self, chosen: str | None) -> None:
        """The months a receipt's services may belong to: the document's own (nothing is
        accrued) or one of the twelve before it, each as its last day."""
        self.expense_month.clear()
        self.expense_month.addItem(tr("месяц документа"), None)
        for last in earlier_months(edited_date(self.date)):
            self.expense_month.addItem(month_name(last[:7]), last)
        if chosen is not None and self.expense_month.findData(chosen) < 0:
            self.expense_month.addItem(month_name(chosen[:7]), chosen)  # saved earlier
        self.expense_month.setCurrentIndex(max(self.expense_month.findData(chosen), 0))
        self._show_expense_month()

    def _expense_months_changed(self, *_args) -> None:
        self._fill_expense_months(self._expense_date())

    def _expense_date(self) -> str | None:
        return self.expense_month.currentData() if self.doc_type == "receipt" else None

    def _show_expense_month(self) -> None:
        """Only a receipt with services (or with a month already chosen) asks for it."""
        shown = self.doc_type == "receipt" and (
            self.model.has_expenses() or self._expense_date() is not None
        )
        self.expense_caption.setVisible(shown)
        self.expense_month.setVisible(shown)

    def _show_currency(self, currency_id: int | None, rate: int | None) -> None:
        receipt = self.doc_type == "receipt"
        self.currency.setCurrentIndex(max(self.currency.findData(currency_id), 0))
        self.rate.setText("" if rate is None else format_unit_rate(unit_rate(rate)))
        self.rate_typed = rate is not None  # a saved rate stays as it was
        for widget in (self.currency_caption, self.currency):
            widget.setVisible(receipt)
        self._apply_currency()

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.doc_type = self.doc.doc_type
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.type_label.setText(tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type)))
        self._show_vat_rate(self.doc.vat_rate)
        vat_rate = self._chosen_vat_rate()
        kinds = sale_kinds(self.s) if self.doc_type == "sale" else []
        rows = [
            InventoryGridRow(
                line.item_id,
                line.warehouse_id,
                line.to_warehouse_id,
                line.quantity or None,
                line.amount or None,
                line.offset_account_id,
                list(line.offset_subconto),
                line.memo,
                line.id,
                vat_amount=line.vat_amount if vat_rate is not None or line.vat_amount else None,
                vat_typed=line.vat_amount != vat_of(line.amount, vat_rate),
                currency_amount=line.currency_amount,
                expense_account_id=line.cost_account_id if self.doc_type == "receipt" else None,
                expense_subconto=(
                    list(line.cost_subconto) if self.doc_type == "receipt" else [None, None, None]
                ),
                sale_subconto=by_sale_kinds(self.s.catalog, kinds, line.cost_subconto),
            )
            for line in self.doc.lines
        ] or [InventoryGridRow()]
        read_only = not self.doc.editable  # a posted document is edited in place, as in 1C
        self.model = InventoryLinesModel(
            self.s, self.doc_type, rows, read_only=read_only, vat_rate=vat_rate
        )
        self.table.setModel(self.model)
        self.table.configure_columns()
        self.expense_columns = self._expense_columns()
        self.delegate = InventoryLinesDelegate(self)
        self._connect_delegate()
        self.table.setItemDelegate(self.delegate)
        self.model.changed.connect(self._changed)
        if self.doc.status == "posted":
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self._apply_mode(read_only)
        self._show_currency(self.doc.currency_id, self.doc.currency_rate)
        self._show_basis(self.doc.invoice_kind, self.doc.invoice)
        self._fill_expense_months(self.doc.expense_date)
        self.dirty = False
        self._show_totals()
        self.title_changed.emit()

    def _apply_mode(self, read_only: bool) -> None:
        self.memo.setReadOnly(read_only)
        self.memo.setEnabled(not read_only)
        self.date.setEnabled(not read_only)
        self.vat_rate.setEnabled(not read_only)
        self.currency.setEnabled(not read_only)
        self.rate.setReadOnly(read_only)
        self.basis.setEnabled(not read_only)
        self.invoice.setReadOnly(read_only)
        self.expense_month.setEnabled(not read_only)
        self.model.read_only = read_only
        posted = self.doc is not None and self.doc.status == "posted"
        editable = not read_only and self.doc_type != "landed_cost"
        self.btn_save.setVisible(editable and not posted)  # Ctrl+S reposts a posted one
        self.btn_post.setVisible(editable)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(posted and self.doc_type != "landed_cost")
        self.btn_gl.setVisible(self.doc is not None and self.doc.gl_document_id is not None)
        self.btn_accrual.setVisible(
            self.doc is not None and self.doc.accrual_document_id is not None
        )
        self.hint.setVisible(not read_only and self.doc_type != "landed_cost")

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def save(self, post: bool) -> bool:
        if self.model.read_only or self.doc_type == "landed_cost":
            return False
        self._finish_editing()
        self.table.setFocus()
        self.error.hide()
        try:
            if self.doc is not None and self.doc.status == "posted":
                # edited in place: posted again at once, later documents recalculated
                post = True
                inputs = self.model.to_inputs(complete=True)
                with self.inventory.reposting(self.s.company_id, self.doc.id):
                    document_id = self._save_draft(inputs)
            else:
                inputs = self.model.to_inputs(complete=post)
                document_id = self._save_draft(inputs)
                if post:
                    self.inventory.post_document(self.s.company_id, document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return False
        self.s.working_date = edited_date(self.date)
        self.load(document_id)
        assert self.doc is not None  # load() has just read it
        self.s.notify(
            tr(
                "Складской документ №{n} проведён" if post else "Складской документ №{n} сохранён",
                n=self.doc.number,
            )
        )
        self.saved.emit(document_id)
        return True

    def _save_draft(self, inputs) -> int:
        company_id = self.s.company_id
        document_date = edited_date(self.date)
        memo = self.memo.text().strip()
        if self.doc_type in {"opening", "receipt"}:
            first = inputs[0]
            if self.doc is None:
                return self.inventory.create_receipt_draft(
                    company_id,
                    document_date,
                    inputs,
                    first.credit_account_id,
                    first.credit_subconto,
                    memo,
                    opening=self.doc_type == "opening",
                    vat_rate=self._chosen_vat_rate(),
                    currency_id=self._chosen_currency(),
                    currency_rate=self._rate_text(),
                    expense_date=self._expense_date(),
                    **self._invoice(),
                )
            self.inventory.update_receipt_draft(
                company_id,
                self.doc.id,
                document_date,
                inputs,
                first.credit_account_id,
                first.credit_subconto,
                memo,
                vat_rate=self._chosen_vat_rate(),
                currency_id=self._chosen_currency(),
                currency_rate=self._rate_text(),
                expense_date=self._expense_date(),
                **self._invoice(),
            )
            return self.doc.id
        if self.doc_type == "sale":
            first = inputs[0]
            header = (first.customer_account_id, first.customer_subconto, memo)
            extra = {"vat_rate": self._chosen_vat_rate(), **self._invoice()}
            if self.doc is None:
                return self.inventory.create_sale_draft(
                    company_id, document_date, inputs, *header, **extra
                )
            self.inventory.update_sale_draft(
                company_id, self.doc.id, document_date, inputs, *header, **extra
            )
            return self.doc.id
        if self.doc_type == "issue":
            if self.doc is None:
                return self.inventory.create_issue_draft(company_id, document_date, inputs, memo)
            self.inventory.update_issue_draft(company_id, self.doc.id, document_date, inputs, memo)
            return self.doc.id
        if self.doc is None:
            return self.inventory.create_transfer_draft(company_id, document_date, inputs, memo)
        self.inventory.update_transfer_draft(company_id, self.doc.id, document_date, inputs, memo)
        return self.doc.id

    def _rate_text(self) -> str | None:
        if self._chosen_currency() is None:
            return None
        return plain_number(self.rate.text()) or None

    def delete(self) -> None:
        if self.doc is None:
            return
        if (
            QMessageBox.question(
                self,
                tr("Удалить складской документ"),
                tr("Удалить складской документ №{n}?", n=self.doc.number),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        number = self.doc.number
        try:
            self.inventory.delete_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.dirty = False
        self.s.notify(tr("Складской документ №{n} удалён", n=number))
        self.saved.emit(self.doc.id)
        self.close_requested.emit()

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.inventory.unpost_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.load(self.doc.id)
        self.s.notify(
            tr(
                "Проведение складского документа №{n} отменено — можно исправлять",
                n=self.doc.number,
            )
        )
        self.saved.emit(self.doc.id)

    def _open_gl(self) -> None:
        if self.doc is not None and self.doc.gl_document_id is not None:
            self.open_gl_document.emit(self.doc.gl_document_id)

    def _open_accrual(self) -> None:
        if self.doc is not None and self.doc.accrual_document_id is not None:
            self.open_gl_document.emit(self.doc.accrual_document_id)
