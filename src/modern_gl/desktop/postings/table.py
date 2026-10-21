"""The postings table and its cell delegate."""

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
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
)

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.cell_editing import (
    TABS,
    TEMPLATE_MARK,
    CellEditor,
    attach_account_list,
    attach_list,
    edit_again,
    edit_current,
    holds_on_group,
    tabbed_in,
)
from modern_gl.desktop.postings.columns import (
    ALIGN_RIGHT,
    AMOUNT,
    CT,
    CURRENCY,
    CURRENCY_AMOUNT,
    CURRENCY_COLUMNS,
    DT,
    INVOICE,
    MEMO,
    RATE,
    EntryHints,
    UnknownValue,
    column_role,
)
from modern_gl.desktop.postings.model import PostingsModel
from modern_gl.desktop.widgets import CutCellTips
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import fold, tr


class PostingsDelegate(QStyledItemDelegate):
    """Line editors with completion for accounts and subconto; Enter = next cell."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text
    template_chosen = Signal(int, int)  # row, entry template id

    def __init__(self, catalog: Catalog, parent=None, hints: EntryHints | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.hints = hints or EntryHints()
        # (kind_id, name, owner_id) -> the new element's id: set by a page that adds to
        # directories; then a subconto list offers "+ Добавить «…»"
        self.add_value: Callable[[int, str, int | None], int] | None = None

    def _template_items(self) -> list[str]:
        return [f"{TEMPLATE_MARK}{name}" for _, name in self.hints.templates()]

    def _subconto_items(self, model, row: int, col: int) -> list[str]:
        """The directory with the elements recently used on this account first."""
        kind = model.kind_at(row, col)
        if kind is None:
            return []
        side, pos = column_role(col)
        values = self.catalog.values(kind, model.owner_at(row, col))
        account = getattr(model.rows[row], side)
        active = {v.id for v in values}
        recent = (
            [v for v in self.hints.recent(account, pos) if v in active]
            if account and pos is not None
            else []
        )
        rest = [v for v in values if v.id not in set(recent)]
        return [self.catalog.value(v).label for v in recent] + [v.label for v in rest]

    def createEditor(self, parent, option, index):
        editor = CellEditor(parent)
        editor.setFrame(False)
        editor.setProperty("gl_row", index.row())
        side, pos = column_role(index.column())
        model = index.model()
        if side in ("debit", "credit") and pos is None:
            items = [a.label for a in self.catalog.leaf_accounts]
            if side == "debit" and not model.formulas:
                items += self._template_items()
            # an account cell shows suggestions from the first typed character
            attach_account_list(editor, items, self.catalog, self._chosen)
        elif side in ("debit", "credit"):
            # a subconto cell opens with its whole list, like a 1C directory
            items = self._subconto_items(model, index.row(), index.column())
            attach_list(editor, items, True, self._chosen, can_add=self.add_value is not None)
        elif side == "currency":
            attach_list(
                editor, [c.label for c in self.catalog.active_currencies], True, self._chosen
            )
        elif model.is_number(index.column()):
            editor.setAlignment(ALIGN_RIGHT)
        # Enter forwarded by an open popup reaches the editor as returnPressed.
        editor.returnPressed.connect(lambda e=editor: self._commit_and_next(e))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        if editor.text():  # keep the key that started editing
            return
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
        model = index.model()
        r = model.rows[index.row()]
        if (
            index.column() == MEMO
            and not r.memo
            and r.debit is not None
            and r.credit is not None
            and not model.read_only
        ):
            hint = self.hints.memo(r.debit, r.credit)
            if hint:  # offered selected: Enter takes it, typing replaces it
                editor.setText(hint)
                editor.selectAll()

    def _template(self, text: str) -> int | None:
        needle = fold(text.strip()[len(TEMPLATE_MARK) :])
        templates = self.hints.templates()
        found = [t for t in templates if fold(t[1]) == needle] or [
            t for t in templates if fold(t[1]).startswith(needle)
        ]
        if len(found) != 1:
            return None
        return found[0][0]

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        if (
            text.startswith(TEMPLATE_MARK)
            and index.column() == DT
            and not model.formulas
            and self.hints.templates()
        ):
            template_id = self._template(text)
            if template_id is None:
                self.error.emit(tr("шаблон «{name}» не найден или не один", name=text[1:]))
            else:
                self.template_chosen.emit(index.row(), template_id)
            return
        try:
            value = model.parse(index.row(), index.column(), editor.text())
        except UnknownValue as e:
            if editor.property("gl_add") and self.add_value is not None:
                owner = model.owner_at(index.row(), index.column())
                model.setData(index, self.add_value(e.kind_id, e.text, owner))
                return
            # the page asks; the cursor waits in this cell for the answer
            editor.setProperty("gl_unknown", True)
            self.unknown_value.emit(QPersistentModelIndex(index), e.kind_id, e.text)
            return
        except (LookupError, ValueError, TypeError, ValidationError) as e:
            self.error.emit(str(e).strip("'\""))
            return
        model.setData(index, value)

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
        ):
            self._commit_and_next(editor)
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Backtab:
            self._commit_and_next(editor, QAbstractItemDelegate.EndEditHint.EditPreviousItem)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor, hint=QAbstractItemDelegate.EndEditHint.EditNextItem) -> None:
        """Enter and Tab alike; a group, or a name its directory lacks, keeps the cell."""
        if editor.property("gl_done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("gl_done", True)
        self.commitData.emit(editor)
        if editor.property("gl_unknown"):
            hint = QAbstractItemDelegate.EndEditHint.NoHint
        self.closeEditor.emit(editor, hint)


class PostingsTable(QTableView):
    def __init__(self, model: PostingsModel, delegate: PostingsDelegate) -> None:
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(delegate)
        hh = self.horizontalHeader()
        for visual, col in enumerate(model.column_order()):
            hh.moveSection(hh.visualIndex(col), visual)
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
        vh = self.verticalHeader()
        vh.setDefaultSectionSize(34)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hh.setHighlightSections(False)
        self.setColumnWidth(DT, 78)
        self.setColumnWidth(CT, 78)
        for col, w in (
            (CURRENCY, 64),
            (CURRENCY_AMOUNT, 110),
            (RATE, 72),
            (AMOUNT, 120),
            (INVOICE, 150),
        ):
            self.setColumnWidth(col, w)
        hh.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        used = model.catalog.used_positions()
        for pos in (1, 2, 3):
            if pos not in used:
                self.setColumnHidden(DT + pos, True)
                self.setColumnHidden(CT + pos, True)
        self._shown: tuple[bool, bool] | None = None
        self._fit_columns()
        model.changed.connect(self._fit_columns)
        model.modelReset.connect(self._fit_columns)

    def _fit_columns(self) -> None:
        """Currency columns appear only while a line is in a currency, the e-qaimə column
        while a line is on a settlement or ƏDV account."""
        m = self.model()
        rows = range(m.rowCount())
        shown = (any(m.in_currency(r) for r in rows), any(m.takes_invoice(r) for r in rows))
        if shown == self._shown:
            return
        self._shown = shown
        for col in CURRENCY_COLUMNS:
            self.setColumnHidden(col, not shown[0])
        self.setColumnHidden(INVOICE, not shown[1])
        self._fit_subconto_widths()

    MEMO_MIN = 200  # the memo keeps room to be read
    SUBCONTO_WIDTH = (100, 180)  # each subconto column, narrowest and widest

    def _fit_subconto_widths(self) -> None:
        """Subconto columns share what the window leaves after the fixed columns and the
        memo: a wide window shows whole names, a narrow one keeps the memo in view."""
        subconto = [
            base + pos
            for base in (DT, CT)
            for pos in (1, 2, 3)
            if not self.isColumnHidden(base + pos)
        ]
        if not subconto:
            return
        fixed = sum(
            self.columnWidth(c)
            for c in range(self.model().columnCount())
            if c not in subconto and c != MEMO and not self.isColumnHidden(c)
        )
        free = self.viewport().width() - self.verticalHeader().width() - fixed - self.MEMO_MIN
        low, high = self.SUBCONTO_WIDTH
        width = max(low, min(high, free // len(subconto)))
        for col in subconto:
            self.setColumnWidth(col, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_subconto_widths()

    def model(self) -> PostingsModel:  # typed accessor
        return cast(PostingsModel, super().model())

    def _last_enabled_column(self, row: int) -> int:
        cols = [
            c
            for c in self.model().column_order()
            if not self.isColumnHidden(c) and self.model().applies(row, c)
        ]
        return cols[-1]

    def _at_end(self, idx: QModelIndex) -> bool:
        return (
            idx.isValid()
            and idx.row() == self.model().rowCount() - 1
            and idx.column() == self._last_enabled_column(idx.row())
        )

    def _new_row(self) -> None:
        m = self.model()
        row = m.insert_row()
        new = m.index(row, self._first_enabled_column(row))
        self.setCurrentIndex(new)
        self.edit(new)

    def closeEditor(self, editor, hint):
        if hint == QAbstractItemDelegate.EndEditHint.EditNextItem and self._at_end(
            self.currentIndex()
        ):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            self._new_row()
            return
        super().closeEditor(editor, hint)

    def edit_next(self, index: QModelIndex | QPersistentModelIndex) -> None:
        """From this cell on to the next one, open for typing (after a question that
        kept the cursor in the cell)."""
        if not index.isValid():
            return
        self.setCurrentIndex(self.model().index(index.row(), index.column()))
        if self._at_end(self.currentIndex()):
            self._new_row()
            return
        new = self.moveCursor(
            QAbstractItemView.CursorAction.MoveNext, Qt.KeyboardModifier.NoModifier
        )
        self.setCurrentIndex(new)
        self.edit(new)

    def edit_again(self, index: QModelIndex | QPersistentModelIndex, text: str) -> None:
        edit_again(self, index, text)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if tabbed_in(event):
            edit_current(self)

    def _first_enabled_column(self, row: int) -> int:
        return next(
            c
            for c in self.model().column_order()
            if not self.isColumnHidden(c) and self.model().applies(row, c)
        )

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            idx = self.currentIndex()
            if idx.isValid() and idx.flags() & Qt.ItemFlag.ItemIsEditable:
                self.edit(idx)
                return
        super().keyPressEvent(event)
        if event.key() in TABS:  # Tab moves on as Enter does: into the next cell, open
            edit_current(self)
