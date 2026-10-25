"""The lines table: its cell editors (lists with search, numbers) and its columns."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
)

from modern_gl.application.inventory import (
    to_quantity,
)
from modern_gl.desktop.cell_editing import (
    TABS,
    CellEditor,
    attach_account_list,
    attach_list,
    edit_again,
    edit_current,
    edit_next,
    holds_on_group,
    resolve_choice,
    tabbed_in,
)
from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    ESC_KEYS,
    EXPENSE,
    EXPENSE_MONTH,
    ITEM,
    ITEM_MIN,
    LIST_KEYS,
    MEMO,
    NARROW_MIN,
    NUMBER_KEYS,
    PRICE,
    QUANTITY,
    SALE_KEYS,
    SC_KEYS,
    SEVERAL_MONTHS,
    SOFT_KEYS,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    WAREHOUSE,
)
from modern_gl.desktop.inventory_document_page.lines_model import (
    InventoryLinesModel,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    CutCellTips,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    stock_account_choices,
    unit_choices,
)


def _widen(editor: QLineEdit) -> None:
    """The editor of a name grows over the next cells to show it whole (up to the
    table's edge), and back to the cell as the text gets shorter."""
    cell = editor.property("cell_width") or editor.width()
    parent = editor.parentWidget()
    room = parent.width() - editor.x() if parent is not None else cell
    need = editor.fontMetrics().horizontalAdvance(editor.text()) + 24
    editor.resize(max(cell, min(need, room)), editor.height())
    editor.raise_()


UNSET = object()  # a cell edit that sets nothing


class InventoryLinesDelegate(QStyledItemDelegate):
    """Enter or Tab commits a cell; a name missing from a directory can be added on the spot."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text
    unknown_item = Signal(QPersistentModelIndex, str)
    # index, name, picked as "+ Добавить «…»" (then added without a question)
    unknown_warehouse = Signal(QPersistentModelIndex, str, bool)
    several_months = Signal(QPersistentModelIndex)  # «несколько месяцев…» picked: split it
    # (kind_id, name, owner_id) -> the new element's id: a subconto list offers
    # "+ Добавить «…»" (see `attach_list`)
    add_value: Callable[[int, str, int | None], int] | None = None

    def createEditor(self, parent, option, index):
        model: InventoryLinesModel = index.model()
        key = model.key(index)
        editor = CellEditor(parent)
        editor.setFrame(False)
        if key in LIST_KEYS:
            # Directory cells open with the whole list; the account list starts with typing.
            labels = [label for _, label in model.choices(index.row(), key)]
            if key in {ACCOUNT, EXPENSE}:
                attach_account_list(editor, labels, model.s.catalog, self._chosen)
            else:
                # a new item or warehouse, like a new contract, is offered in the list
                can_add = key in (ITEM, WAREHOUSE) or (
                    key in SUBCONTO_KEYS and self.add_value is not None
                )
                attach_list(editor, labels, True, self._chosen, can_add=can_add)
        elif key in NUMBER_KEYS:
            editor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if key == ITEM:  # a long name of an e-qaimə line is seen whole while edited
            editor.textChanged.connect(lambda _text, widget=editor: _widen(widget))
        editor.returnPressed.connect(lambda widget=editor: self._commit_and_next(widget))
        return editor

    def updateEditorGeometry(self, editor, option, index):
        super().updateEditorGeometry(editor, option, index)
        if index.model().key(index) == ITEM:
            editor.setProperty("cell_width", editor.width())
            _widen(editor)

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        model: InventoryLinesModel = index.model()
        value = index.data(Qt.ItemDataRole.EditRole)
        if model.key(index) == ITEM and model.is_service(index.row()):
            value = model.rows[index.row()].memo  # what the service is, to read or correct
        elif model.key(index) in LIST_KEYS:
            value = "" if value is None else index.data(Qt.ItemDataRole.DisplayRole)
        editor.setText(value or "")
        editor.selectAll()

    def _subconto_value(self, editor, model, index, key: str, text: str) -> object:
        """The element named; one its directory lacks is added when picked as
        "+ Добавить «…»", else the page is told. UNSET: nothing to set."""
        kind_id = model.kind_at(index.row(), key)
        if kind_id is None:  # the account has no subconto at this position
            return UNSET
        owner = model.owner_at(index.row(), key)
        value = model.s.catalog.resolve_value(kind_id, text, owner) if text else None
        if not text or value is not None:
            return value
        if editor.property("gl_add") and self.add_value is not None:
            return self.add_value(kind_id, text, owner)
        editor.setProperty("gl_unknown", True)  # the cursor waits in the cell for the answer
        self.unknown_value.emit(QPersistentModelIndex(index), kind_id, text)
        return UNSET

    def _list_value(self, editor, model, index, key: str, text: str) -> object:
        """The item, warehouse or account named; a name the list lacks is asked about
        (UNSET: nothing to set now). A service's corrected name stays its memo."""
        value = resolve_choice(model.choices(index.row(), key), text) if text else None
        if key == ITEM and text and value is None and model.is_service(index.row()):
            model.setData(model.index(index.row(), model.columns.index(MEMO)), text)
            return UNSET
        if text and value is None:
            editor.setProperty("gl_unknown", True)  # the cell waits for the answer
            where = QPersistentModelIndex(index)
            if key == ITEM:
                self.unknown_item.emit(where, text)
            else:
                self.unknown_warehouse.emit(where, text, bool(editor.property("gl_add")))
            return UNSET
        return value

    def setModelData(self, editor, model, index):
        model = cast(InventoryLinesModel, model)
        key = model.key(index)
        text = editor.text().strip()
        try:
            if key in {ACCOUNT, EXPENSE}:
                value = model.s.catalog.resolve_account(text).id if text else None
            elif key in SUBCONTO_KEYS:
                value = self._subconto_value(editor, model, index, key, text)
                if value is UNSET:  # no subconto here, or the page asks about the name
                    return
            elif key == EXPENSE_MONTH:
                value = model.month_code_of(text) if text else None
                if value == SEVERAL_MONTHS:
                    editor.setProperty("gl_unknown", True)  # the page asks for the months
                    self.several_months.emit(QPersistentModelIndex(index))
                    return
            elif key in LIST_KEYS:
                value = self._list_value(editor, model, index, key, text)
                if value is UNSET:
                    return
            elif key == QUANTITY:
                value = to_quantity(text) if text else None
            elif key in {PRICE, AMOUNT, VAT, CURRENCY_AMOUNT}:
                value = to_minor(text) if text else None
                if value is not None and (value < 0 or (value == 0 and key != VAT)):  # VAT 0 ok
                    raise ValueError(tr("сумма должна быть больше нуля"))
            else:
                value = text
            model.setData(index, value)
        except (LedgerError, LookupError, ValueError, TypeError) as exc:
            self.error.emit(str(exc).strip("'\""))

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
        ):
            self._commit_and_next(editor)  # Tab as Enter: a group holds the cell
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backtab:
            self._commit_and_next(editor, QAbstractItemDelegate.EndEditHint.EditPreviousItem)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor, hint=QAbstractItemDelegate.EndEditHint.EditNextItem) -> None:
        """Enter and Tab alike; a group, or a name its directory lacks, keeps the cell."""
        if editor.property("inventory_done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("inventory_done", True)
        self.commitData.emit(editor)
        if editor.property("gl_unknown"):
            hint = QAbstractItemDelegate.EndEditHint.NoHint
        self.closeEditor.emit(editor, hint)


class InventoryLinesTable(QTableView):
    def __init__(self, model: InventoryLinesModel, delegate: InventoryLinesDelegate) -> None:
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.setShowGrid(False)
        self.setWordWrap(False)
        CutCellTips(self)
        self.setTabKeyNavigation(True)
        self.verticalHeader().setDefaultSectionSize(34)
        self.configure_columns()

    def edit_again(self, index: QModelIndex | QPersistentModelIndex, text: str) -> None:
        edit_again(self, index, text)

    def edit_next(self, index: QModelIndex | QPersistentModelIndex) -> None:
        edit_next(self, index)

    def configure_columns(self) -> None:
        model = self.model()
        # Fits an ordinary window without a horizontal scroll bar: the item name takes
        # what is left; subconto positions no account uses are not shown.
        widths = {
            WAREHOUSE: 110,
            TO_WAREHOUSE: 110,
            QUANTITY: 100,
            UNIT: 64,
            PRICE: 84,
            AMOUNT: 96,
            CURRENCY_AMOUNT: 104,
            VAT: 84,
            ACCOUNT: 130,
            EXPENSE: 130,
            EXPENSE_MONTH: 120,
            **dict.fromkeys(SALE_KEYS, 130),  # named after its directory: «Satış qrupları»
        }
        used = model.s.catalog.used_positions()
        expenses = model.has_expenses()
        goods = model.has_goods()
        expense_positions = model.expense_positions()
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        self._widths = {
            key: widths.get(key, 100 if key in SUBCONTO_KEYS else 120) for key in model.columns
        }
        for column, key in enumerate(model.columns):
            self.setColumnWidth(column, self._widths[key])
            self.setColumnHidden(column, False)  # a column of the previous model may be hidden
            if key in SC_KEYS:
                self.setColumnHidden(column, int(key[-1]) not in used)
            if key in {WAREHOUSE, UNIT}:
                self.setColumnHidden(column, not goods)
            if key in {EXPENSE, EXPENSE_MONTH}:
                self.setColumnHidden(column, not expenses)
            if key == ACCOUNT:
                self.setColumnHidden(column, model.accounts_hidden)
            if key in ESC_KEYS:
                self.setColumnHidden(column, not expenses or int(key[-1]) not in expense_positions)
            if key in SALE_KEYS:
                self.setColumnHidden(
                    column, not any(model.applies(r, key) for r in range(model.rowCount()))
                )
            if key == VAT:
                self.setColumnHidden(column, not model.has_vat())
            if key == CURRENCY_AMOUNT:
                self.setColumnHidden(column, not model.has_currency)
            if key == ITEM:  # its width is what is left (`_fit_columns`)
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self._fit_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """The name takes what is left and keeps ITEM_MIN px: in a narrow window the
        account, subconto and warehouse columns give up width first (their text gets «…»),
        down to NARROW_MIN; narrower still, the table scrolls — the name is not crushed."""
        model = self.model()
        widths = getattr(self, "_widths", None)
        if not widths:
            return
        shown = [
            (column, key)
            for column, key in enumerate(model.columns)
            if key != ITEM and not self.isColumnHidden(column)
        ]
        soft = [(column, key) for column, key in shown if key in SOFT_KEYS]
        fixed = sum(widths[key] for _, key in shown if key not in SOFT_KEYS)
        room = self.viewport().width() - fixed - ITEM_MIN
        wanted = sum(widths[key] for _, key in soft)
        scale = 1.0 if wanted <= 0 or room >= wanted else max(room, 0) / wanted
        for column, key in soft:
            self.setColumnWidth(column, max(NARROW_MIN, int(widths[key] * scale)))
        others = sum(self.columnWidth(column) for column, _ in shown)
        item = model.columns.index(ITEM)
        self.setColumnWidth(item, max(ITEM_MIN, self.viewport().width() - others))

    def model(self) -> InventoryLinesModel:
        return cast(InventoryLinesModel, super().model())

    def closeEditor(self, editor, hint):
        index = self.currentIndex()
        model = self.model()
        if not index.isValid():
            super().closeEditor(editor, hint)
            return
        editable = [
            column
            for column, key in enumerate(model.columns)
            if not self.isColumnHidden(column)
            and model.editable(key)
            and model.applies(index.row(), key)
        ]
        if (
            hint == QAbstractItemDelegate.EndEditHint.EditNextItem
            and index.isValid()
            and not model.read_only
            and index.row() == model.rowCount() - 1
            and editable
            and index.column() == editable[-1]
        ):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            row = model.insert_row()
            new_index = model.index(row, 0)
            self.setCurrentIndex(new_index)
            self.edit(new_index)
            return
        super().closeEditor(editor, hint)

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            index = self.currentIndex()
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEditable:
                self.edit(index)
                return
        super().keyPressEvent(event)
        if event.key() in TABS:  # Tab moves on as Enter does: into the next cell, open
            edit_current(self)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if tabbed_in(event):
            edit_current(self)


class NewNamesDialog(QDialog):
    """Names pasted from Excel that are not in the lists yet: add them all at once.
    New items need a unit (pick one or type a new one) and a stock account."""

    def __init__(self, session: Session, listing: str, items: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Новые элементы справочников"))
        self.setMinimumWidth(440)
        form = QFormLayout(self)
        text = QLabel(tr("Этих элементов нет в справочниках. Добавить?\n\n{names}", names=listing))
        text.setWordWrap(True)
        form.addRow(text)
        self.unit = QComboBox()
        self.unit.setEditable(True)
        for unit in unit_choices(session.conn, session.company_id):
            self.unit.addItem(unit.label, unit.id)
        if not self.unit.count():
            self.unit.setEditText(tr("шт"))
        self.account = QComboBox()
        for account in stock_account_choices(session.conn, session.company_id):
            self.account.addItem(account.label, account.id)
        if items:
            form.addRow(tr("Единица новых товаров"), self.unit)
            form.addRow(tr("Счёт запасов"), self.account)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
