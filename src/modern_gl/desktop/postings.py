"""Postings grid: model, inline editors with completion, keyboard flow.

Keyboard flow (1C-like): type into a cell to edit, Enter/Tab moves to the next cell
that applies — subconto cells the chosen account doesn't have are skipped, and so
are the currency cells of a line without a currency account. On a currency line the
amount in manat follows the amount in currency at the rate (the rate of the document
date is offered; both the rate and the manat amount can be typed over).
Enter on the last cell of the last row starts a new row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
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
from modern_gl.domain import formula
from modern_gl.domain.currency import format_unit_rate, parse_rate, to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import SCALE, format_minor, to_minor
from modern_gl.i18n import tr

DT, CT, CURRENCY, CURRENCY_AMOUNT, RATE, AMOUNT, MEMO = 0, 4, 8, 9, 10, 11, 12
CURRENCY_COLUMNS = (CURRENCY, CURRENCY_AMOUNT, RATE)
HEADERS = [
    "Дебет",
    "Субконто",
    "",
    "",
    "Кредит",
    "Субконто",
    "",
    "",
    "Валюта",
    "В валюте",
    "Курс",
    "Сумма",
    "Содержание",
]
NUMBER_COLUMNS = (CURRENCY_AMOUNT, RATE, AMOUNT)
# translated at display time: tr(HEADERS[i])
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def column_role(col: int) -> tuple[str, int | None]:
    """('debit'|'credit', None) for an account, (side, 1..3) for subconto, else field name."""
    if DT <= col < CT:
        return "debit", (col - DT) or None
    if CT <= col < CURRENCY:
        return "credit", (col - CT) or None
    names = {
        CURRENCY: "currency",
        CURRENCY_AMOUNT: "currency_amount",
        RATE: "rate",
        AMOUNT: "amount",
    }
    return names.get(col, "memo"), None


@dataclass
class PostingRow:
    debit: int | None = None
    debit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    credit: int | None = None
    credit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    memo: str = ""
    formula: str = ""  # entry templates: amount formula (S, S*18/118…), see domain.formula
    currency_id: int | None = None
    currency_amount: int | None = None
    rate: Fraction | None = None  # manat per unit; the manat amount follows it
    rate_auto: bool = True  # taken from the rates of the document date (not typed)

    def is_empty(self) -> bool:
        return (
            self.debit is None
            and self.credit is None
            and self.amount is None
            and not self.formula
            and not self.memo.strip()
        )

    @classmethod
    def from_data(cls, p: PostingData, keep_sign: bool = True) -> PostingRow:
        cur = p.currency_amount
        return cls(
            p.debit_account_id,
            list(p.debit_subconto),
            p.credit_account_id,
            list(p.credit_subconto),
            p.amount if keep_sign else abs(p.amount),
            p.memo,
            currency_id=p.currency_id,
            currency_amount=cur if keep_sign or cur is None else abs(cur),
            rate=Fraction(p.amount, cur) if cur else None,  # as it was posted
            rate_auto=False,
        )


class PostingsModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        catalog: Catalog,
        rows: list[PostingRow] | None = None,
        read_only: bool = False,
        formulas: bool = False,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.rows = rows or [PostingRow()]
        self.read_only = read_only
        self.formulas = formulas  # template editing: the amount column holds formulas
        # currency id -> manat per unit on the document date (set by the document page)
        self.rate_for: Callable[[int], Fraction | None] = lambda _currency_id: None

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
            return ALIGN_RIGHT if section in NUMBER_COLUMNS else ALIGN_LEFT
        return None

    def is_currency(self, row: int) -> bool:
        """The line hits a currency account, so it has a currency and an amount in it."""
        r = self.rows[row]
        return not self.formulas and any(
            a is not None and self.catalog.accounts[a].currency for a in (r.debit, r.credit)
        )

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
        if col in CURRENCY_COLUMNS:
            return self.is_currency(row)
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
                    return self.catalog.accounts[account_id].short if account_id else ""
                value_id = getattr(r, f"{side}_sc")[pos - 1]
                if value_id is not None:
                    return self.catalog.value(value_id).name
                kind = self.kind_at(index.row(), col)
                if kind is None or role != Qt.ItemDataRole.DisplayRole or self.read_only:
                    return ""
                return self.catalog.kinds[kind]
            if side == "currency":
                currency = self.catalog.currencies.get(r.currency_id or 0)
                return currency.code if currency and self.is_currency(index.row()) else ""
            if side == "currency_amount":
                if r.currency_amount is None or not self.is_currency(index.row()):
                    return ""
                text = format_minor(r.currency_amount)
                return text if role == Qt.ItemDataRole.DisplayRole else text.replace(" ", "")
            if side == "rate":
                if r.rate is None or not self.is_currency(index.row()):
                    return ""
                return format_unit_rate(r.rate)
            if side == "amount":
                if self.formulas:
                    return r.formula
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
            if side in ("amount", "currency_amount") and (
                getattr(r, side) is not None and getattr(r, side) < 0
            ):
                return QColor(P.red)
            if side == "rate":
                return QColor(P.secondary)
        if role == Qt.ItemDataRole.FontRole and pos is not None:
            if getattr(r, f"{side}_sc")[pos - 1] is None:
                f = QFont()
                f.setItalic(True)
                return f
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGN_RIGHT if col in NUMBER_COLUMNS else ALIGN_LEFT
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
                self._fit_currency(index.row())
                self._row_changed(index.row())
            else:
                getattr(r, f"{side}_sc")[pos - 1] = value
                self._fit_currency(index.row())
                self._row_changed(index.row())
        elif side == "currency":
            r.currency_id = value
            r.rate_auto = True
            r.rate = self.rate_for(value) if value is not None else None
            self._follow_rate(r)
            self._row_changed(index.row())
        elif side == "currency_amount":
            r.currency_amount = value
            self._follow_rate(r)
            self._row_changed(index.row())
        elif side == "rate":
            r.rate = value
            r.rate_auto = value is None
            if value is None and r.currency_id is not None:
                r.rate = self.rate_for(r.currency_id)
            self._follow_rate(r)
            self._row_changed(index.row())
        elif side == "amount" and self.formulas:
            r.formula = value
            self.dataChanged.emit(index, index)
        elif side == "amount":
            r.amount = value
            r.formula = ""  # typed by hand: no longer follows the operation amount
            self.dataChanged.emit(index, index)
        else:
            r.memo = value
            self.dataChanged.emit(index, index)
        self.changed.emit()
        return True

    # ---- currency ----------------------------------------------------------------------

    def _row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))

    def _fit_currency(self, row: int) -> None:
        """After an account or subconto changes: a line without currency accounts drops
        its currency; a currency line takes the currency of a chosen element (a USD bank
        account, a contract in EUR) when it has one."""
        r = self.rows[row]
        if not self.is_currency(row):
            r.currency_id = r.currency_amount = r.rate = None
            r.rate_auto = True
            return
        for side in ("debit", "credit"):
            account_id = getattr(r, side)
            if account_id is None or not self.catalog.accounts[account_id].currency:
                continue
            for value_id in getattr(r, f"{side}_sc"):
                currency_id = self.catalog.value(value_id).currency_id if value_id else None
                if currency_id is not None and currency_id != r.currency_id:
                    r.currency_id, r.rate_auto = currency_id, True
                    r.rate = self.rate_for(currency_id)
                    self._follow_rate(r)
                    return

    @staticmethod
    def _follow_rate(r: PostingRow) -> None:
        """The manat amount = amount in currency × rate."""
        if r.currency_amount is not None and r.rate is not None:
            r.amount = to_base(r.currency_amount, r.rate) or None
            r.formula = ""

    def refresh_rates(self) -> None:
        """The document date changed: lines on the offered rate take the new day's rate."""
        for row, r in enumerate(self.rows):
            if r.currency_id is not None and r.rate_auto:
                r.rate = self.rate_for(r.currency_id)
                self._follow_rate(r)
                self._row_changed(row)
        self.changed.emit()

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
                src.debit,
                list(src.debit_sc),
                src.credit,
                list(src.credit_sc),
                src.amount,
                src.memo,
                src.formula,
                src.currency_id,
                src.currency_amount,
                src.rate,
                src.rate_auto,
            ),
        )

    def recalculate(self, total: int | None) -> str | None:
        """Set the amounts of rows that have a formula for the operation amount S.
        Rows typed by hand take part with their amount. Returns an error text, if any."""
        if not any(r.formula for r in self.rows):
            return None
        sources = [
            r.formula or (format_minor(r.amount).replace(" ", "") if r.amount else "")
            for r in self.rows
        ]
        try:
            amounts = formula.compute(sources, total) if total else [None] * len(sources)
        except ValidationError as e:
            return str(e)
        for r, amount in zip(self.rows, amounts, strict=True):
            if r.formula:
                r.amount = amount if amount and amount > 0 else None
        self.dataChanged.emit(self.index(0, AMOUNT), self.index(len(self.rows) - 1, AMOUNT))
        self.changed.emit()
        return None

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
            currency = self.is_currency(n - 1) and r.currency_id is not None
            result.append(
                PostingInput(
                    r.debit,
                    r.credit,
                    Decimal(r.amount).scaleb(-SCALE),
                    tuple(r.debit_sc),
                    tuple(r.credit_sc),
                    r.memo.strip(),
                    r.currency_id if currency else None,
                    Decimal(r.currency_amount or 0).scaleb(-SCALE) if currency else None,
                )
            )
        if not result:
            raise ValidationError(tr("в документе нет проводок"))
        return result


class _PickWithKeys(QObject):
    """On the open list, Enter or Tab takes the highlighted item."""

    KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab)

    def __init__(self, popup, choose) -> None:
        super().__init__(popup)
        self.choose = choose
        popup.installEventFilter(self)  # installed after QCompleter's, so it runs first

    def eventFilter(self, popup, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() in self.KEYS:
            index = popup.currentIndex()
            if popup.isVisible() and index.isValid():
                popup.hide()
                self.choose(index.data())
                return True
        return False


def attach_list(editor: QLineEdit, items: list[str], show_all: bool, chosen) -> None:
    """Completion list under a cell editor; `chosen(editor, text)` gets the picked item."""
    model = QStringListModel(editor)
    completer = QCompleter(model, editor)
    completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
    completer.setMaxVisibleItems(12)
    completer.setWidget(editor)  # filtering is ours (search), not Qt's prefix matching
    popup = cast(QAbstractItemView, completer.popup())
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

    editor.textEdited.connect(refresh)
    # mouse click; the str overload of the signal is not in the PySide6 stubs
    completer.activated[str].connect(  # pyright: ignore[reportIndexIssue]
        lambda text: chosen(editor, text)
    )
    # Enter / Tab on a highlighted item: Qt would hand the key to the editor *before*
    # reporting the choice, so the editor would commit what was typed (often nothing).
    _PickWithKeys(popup, lambda text: chosen(editor, text))
    QTimer.singleShot(0, lambda: refresh(editor.text()))


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
            attach_list(editor, items, pos is not None, self._chosen)
        elif side == "currency":
            attach_list(
                editor, [c.label for c in self.catalog.active_currencies], True, self._chosen
            )
        elif index.column() in NUMBER_COLUMNS:
            editor.setAlignment(ALIGN_RIGHT)
        # Enter forwarded by an open popup reaches the editor as returnPressed.
        editor.returnPressed.connect(lambda e=editor: self._commit_and_next(e))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

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
            elif side == "currency":
                value = self.catalog.resolve_currency(text).id if text else None
            elif side == "currency_amount":
                value = to_minor(text) if text else None
                if value is not None and value <= 0:
                    raise ValueError(tr("сумма должна быть больше нуля"))
            elif side == "rate":
                value = unit_rate(parse_rate(text)) if text else None
            elif side == "amount" and model.formulas:
                if text:
                    formula.parse(text)  # check now, not when the template is saved
                value = text
            elif side == "amount":
                value = to_minor(text) if text else None
                if value is not None and value <= 0:
                    raise ValueError(tr("сумма должна быть больше нуля"))
            else:
                value = text
        except (LookupError, ValueError, TypeError, ValidationError) as e:
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
        self.setColumnWidth(DT, 78)
        self.setColumnWidth(CT, 78)
        for col, w in ((CURRENCY, 64), (CURRENCY_AMOUNT, 110), (RATE, 72), (AMOUNT, 120)):
            self.setColumnWidth(col, w)
        hh.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        used = model.catalog.used_positions()
        for pos in (1, 2, 3):
            if pos not in used:
                self.setColumnHidden(DT + pos, True)
                self.setColumnHidden(CT + pos, True)
        self._currency_shown: bool | None = None
        self._fit_currency_columns()
        model.changed.connect(self._fit_currency_columns)
        model.modelReset.connect(self._fit_currency_columns)

    def _fit_currency_columns(self) -> None:
        """Currency columns appear only while a line hits a currency account; then the
        subconto columns get narrower, so the amount and memo stay in view."""
        m = self.model()
        show = any(m.is_currency(r) for r in range(m.rowCount()))
        if show == self._currency_shown:
            return
        self._currency_shown = show
        for col in CURRENCY_COLUMNS:
            self.setColumnHidden(col, not show)
        widths = (120, 100, 90) if show else (160, 140, 120)
        for base in (DT, CT):
            for pos, w in enumerate(widths, start=1):
                self.setColumnWidth(base + pos, w)

    def model(self) -> PostingsModel:  # typed accessor
        return cast(PostingsModel, super().model())

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
