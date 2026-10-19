"""Postings grid: model, inline editors with completion, keyboard flow.

Keyboard flow (1C-like): type into a cell to edit, Enter/Tab moves to the next cell
that applies — subconto cells the chosen account doesn't have are skipped.
Enter on the last cell of the last row starts a new row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QStringListModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QCompleter,
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
)

from modern_gl.application.catalog import Catalog, search
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import PostingData
from modern_gl.desktop.theme import P
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import SCALE, format_minor, to_minor
from modern_gl.i18n import tr

DT, CT, AMOUNT, MEMO = 0, 4, 8, 9
HEADERS = ["Дебет", "Субконто", "", "", "Кредит", "Субконто", "", "", "Сумма", "Содержание"]
# translated at display time: tr(HEADERS[i])
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def column_role(col: int) -> tuple[str, int | None]:
    """('debit'|'credit', None) for an account, (side, 1..3) for subconto, else field name."""
    if DT <= col < CT:
        return "debit", (col - DT) or None
    if CT <= col < AMOUNT:
        return "credit", (col - CT) or None
    return ("amount", None) if col == AMOUNT else ("memo", None)


@dataclass
class PostingRow:
    debit: int | None = None
    debit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    credit: int | None = None
    credit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    memo: str = ""

    def is_empty(self) -> bool:
        return (
            self.debit is None
            and self.credit is None
            and self.amount is None
            and not self.memo.strip()
        )

    @classmethod
    def from_data(cls, p: PostingData, keep_sign: bool = True) -> PostingRow:
        return cls(
            p.debit_account_id,
            list(p.debit_subconto),
            p.credit_account_id,
            list(p.credit_subconto),
            p.amount if keep_sign else abs(p.amount),
            p.memo,
        )


class PostingsModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self, catalog: Catalog, rows: list[PostingRow] | None = None, read_only: bool = False
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.rows = rows or [PostingRow()]
        self.read_only = read_only

    # ---- Qt model API ----------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return tr(HEADERS[section]) if HEADERS[section] else ""
            return str(section + 1)
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return ALIGN_RIGHT if section == AMOUNT else ALIGN_LEFT
        return None

    def kind_at(self, row: int, col: int) -> int | None:
        """Subconto kind required at this cell, or None if the cell doesn't apply."""
        side, pos = column_role(col)
        if pos is None:
            return None
        account_id = getattr(self.rows[row], side)
        if account_id is None:
            return None
        return self.catalog.accounts[account_id].sc_kinds[pos - 1]

    def applies(self, row: int, col: int) -> bool:
        side, pos = column_role(col)
        return pos is None or self.kind_at(row, col) is not None

    def flags(self, index):
        if not self.applies(index.row(), index.column()):
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.read_only:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r, col = self.rows[index.row()], index.column()
        side, pos = column_role(col)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if side in ("debit", "credit"):
                if pos is None:
                    account_id = getattr(r, side)
                    return self.catalog.accounts[account_id].code if account_id else ""
                value_id = getattr(r, f"{side}_sc")[pos - 1]
                if value_id is not None:
                    return self.catalog.value(value_id).name
                kind = self.kind_at(index.row(), col)
                show_hint = role == Qt.ItemDataRole.DisplayRole and kind and not self.read_only
                return self.catalog.kinds[kind] if show_hint else ""
            if side == "amount":
                if r.amount is None:
                    return ""
                return (
                    format_minor(r.amount)
                    if role == Qt.ItemDataRole.DisplayRole
                    else (format_minor(r.amount).replace(" ", ""))
                )
            return r.memo
        if role == Qt.ItemDataRole.ForegroundRole:
            if pos is not None and getattr(r, f"{side}_sc")[pos - 1] is None:
                return QColor(P.tertiary)  # placeholder with the subconto kind name
            if side == "amount" and r.amount is not None and r.amount < 0:
                return QColor(P.red)
        if role == Qt.ItemDataRole.FontRole and pos is not None:
            if getattr(r, f"{side}_sc")[pos - 1] is None:
                f = QFont()
                f.setItalic(True)
                return f
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGN_RIGHT if side == "amount" else ALIGN_LEFT
        if role == Qt.ItemDataRole.ToolTipRole and side in ("debit", "credit") and pos is None:
            account_id = getattr(r, side)
            return self.catalog.accounts[account_id].label if account_id else None
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        r, col = self.rows[index.row()], index.column()
        side, pos = column_role(col)
        if side in ("debit", "credit"):
            if pos is None:
                setattr(r, side, value)
                kinds = self.catalog.accounts[value].sc_kinds if value else (None, None, None)
                sc = getattr(r, f"{side}_sc")
                for i, kind in enumerate(kinds):
                    if sc[i] is not None and (
                        kind is None or self.catalog.value(sc[i]).kind_id != kind
                    ):
                        sc[i] = None
                self.dataChanged.emit(
                    self.index(index.row(), 0), self.index(index.row(), len(HEADERS) - 1)
                )
            else:
                getattr(r, f"{side}_sc")[pos - 1] = value
                self.dataChanged.emit(index, index)
        elif side == "amount":
            r.amount = value
            self.dataChanged.emit(index, index)
        else:
            r.memo = value
            self.dataChanged.emit(index, index)
        self.changed.emit()
        return True

    # ---- row operations --------------------------------------------------------------

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row or PostingRow())
        self.endInsertRows()
        self.changed.emit()
        return at

    def duplicate_row(self, i: int) -> int:
        src = self.rows[i]
        return self.insert_row(
            i + 1,
            PostingRow(
                src.debit, list(src.debit_sc), src.credit, list(src.credit_sc), src.amount, src.memo
            ),
        )

    def remove_row(self, i: int) -> None:
        self.beginRemoveRows(QModelIndex(), i, i)
        del self.rows[i]
        self.endRemoveRows()
        if not self.rows:
            self.insert_row()
        self.changed.emit()

    def total(self) -> int:
        return sum(abs(r.amount or 0) for r in self.rows)

    def to_inputs(self) -> list[PostingInput]:
        result = []
        for n, r in enumerate(self.rows, start=1):
            if r.is_empty():
                continue
            if r.debit is None:
                raise ValidationError(tr("строка {line}: не указан счёт дебета", line=n))
            if r.credit is None:
                raise ValidationError(tr("строка {line}: не указан счёт кредита", line=n))
            if r.amount is None:
                raise ValidationError(tr("строка {line}: не указана сумма", line=n))
            result.append(
                PostingInput(
                    r.debit,
                    r.credit,
                    Decimal(r.amount).scaleb(-SCALE),
                    tuple(r.debit_sc),
                    tuple(r.credit_sc),
                    r.memo.strip(),
                )
            )
        if not result:
            raise ValidationError(tr("в документе нет проводок"))
        return result


class PostingsDelegate(QStyledItemDelegate):
    """Line editors with completion for accounts and subconto; Enter = next cell."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text

    def __init__(self, catalog: Catalog, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        side, pos = column_role(index.column())
        if side in ("debit", "credit"):
            if pos is None:
                items = [a.label for a in self.catalog.leaf_accounts]
            else:
                kind = index.model().kind_at(index.row(), index.column())
                items = [v.label for v in self.catalog.values(kind)]
            # A subconto cell opens with its whole list, like a 1C directory;
            # an account cell shows suggestions from the first typed character.
            self._attach_list(editor, items, show_all=pos is not None)
        elif side == "amount":
            editor.setAlignment(ALIGN_RIGHT)
        # Enter forwarded by an open popup reaches the editor as returnPressed.
        editor.returnPressed.connect(lambda e=editor: self._commit_and_next(e))
        return editor

    def _attach_list(self, editor: QLineEdit, items: list[str], show_all: bool) -> None:
        model = QStringListModel(editor)
        completer = QCompleter(model, editor)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.setWidget(editor)  # filtering is ours (search), not Qt's prefix matching
        popup = completer.popup()
        popup.setObjectName("completer")

        def refresh(text: str) -> None:
            try:
                typed = bool(text.strip())
                matches = search(items, text) if (typed or show_all) else []
                model.setStringList(matches)
                if not matches:
                    popup.hide()
                    return
                rect = editor.rect()
                rect.setWidth(max(rect.width(), 380))
                completer.complete(rect)
                if typed:  # Enter takes the best match
                    popup.setCurrentIndex(model.index(0))
            except RuntimeError:  # editor already closed
                pass

        def chosen(text: str) -> None:
            editor.setText(text)
            self._commit_and_next(editor)

        editor.textEdited.connect(refresh)
        completer.activated.connect(chosen)
        QTimer.singleShot(0, lambda: refresh(editor.text()))

    def setEditorData(self, editor, index):
        if not editor.text():  # keep the key that started editing
            editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        side, pos = column_role(index.column())
        try:
            if side in ("debit", "credit") and pos is None:
                value = self.catalog.resolve_account(text).id if text else None
            elif side in ("debit", "credit"):
                kind = model.kind_at(index.row(), index.column())
                value = self.catalog.resolve_value(kind, text) if text else None
                if text and value is None:
                    self.unknown_value.emit(QPersistentModelIndex(index), kind, text)
                    return
            elif side == "amount":
                value = to_minor(text) if text else None
                if value is not None and value <= 0:
                    raise ValueError(tr("сумма должна быть больше нуля"))
            else:
                value = text
        except (LookupError, ValueError, TypeError) as e:
            self.error.emit(str(e).strip("'\""))
            return
        model.setData(index, value)

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self._commit_and_next(editor)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor) -> None:
        if editor.property("gl_done"):
            return
        editor.setProperty("gl_done", True)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.EditNextItem)


class PostingsTable(QTableView):
    def __init__(self, model: PostingsModel, delegate: PostingsDelegate) -> None:
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
        self.setTabKeyNavigation(True)
        vh = self.verticalHeader()
        vh.setDefaultSectionSize(34)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        widths = {DT: 78, 1: 160, 2: 140, 3: 120, CT: 78, 5: 160, 6: 140, 7: 120, AMOUNT: 120}
        for col, w in widths.items():
            self.setColumnWidth(col, w)
        hh.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        used = model.catalog.used_positions()
        for pos in (1, 2, 3):
            if pos not in used:
                self.setColumnHidden(DT + pos, True)
                self.setColumnHidden(CT + pos, True)

    def model(self) -> PostingsModel:  # typed accessor
        return super().model()

    def _last_enabled_column(self, row: int) -> int:
        cols = [
            c
            for c in range(len(HEADERS))
            if not self.isColumnHidden(c) and self.model().applies(row, c)
        ]
        return cols[-1]

    def closeEditor(self, editor, hint):
        idx = self.currentIndex()
        m = self.model()
        if (
            hint == QAbstractItemDelegate.EndEditHint.EditNextItem
            and idx.isValid()
            and idx.row() == m.rowCount() - 1
            and idx.column() == self._last_enabled_column(idx.row())
        ):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            row = m.insert_row()
            new = m.index(row, DT)
            self.setCurrentIndex(new)
            self.edit(new)
            return
        super().closeEditor(editor, hint)

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
