"""The quick entry line above the journal: type a document as text, see how it is
understood, Enter posts it (see application.quick_entry for the syntax).

While typing, a list offers what fits at the cursor — accounts, then the elements of
their subconto (after "26 " the cost items), currencies, templates — so the syntax need
not be remembered: Enter or Tab takes the highlighted item and adds what comes next."""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from typing import cast

from PySide6.QtCore import QModelIndex, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application import quick_entry
from modern_gl.application.common import pad_subconto
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import (
    DocumentData,
    PostingData,
    list_templates,
    load_document,
    recent_subconto,
)
from modern_gl.desktop.cell_editing import PickWithKeys, fit_popup
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

HELP = (
    "Enter — провести   ·   Shift+Enter — черновик   ·   Ctrl+Enter — открыть в форме   ·   "
    "↑ — прошлые строки   ·   «+Имя» — новый элемент справочника   ·   Esc — скрыть список"
)


class QuickEntryBar(QWidget):
    posted = Signal(int)  # document id
    open_form = Signal(object)  # DocumentData to finish in the document form

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        self.history: list[str] = []
        self._back = 0  # position while walking the history with ↑ / ↓
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("quickEntry")
        self.edit.setFont(fonts().body)
        self.edit.setPlaceholderText(
            tr("Быстрый ввод:  26 аренда / 60 альфа 400 Аренда за март      Ctrl+L")
        )
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.preview = QLabel()
        self.preview.setObjectName("secondary")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.preview)
        self.help = QLabel(tr(HELP))
        self.help.setObjectName("tertiary")
        self.help.setFont(fonts().small)
        lay.addWidget(self.help)
        self.preview.hide()
        self.help.hide()
        self.edit.textChanged.connect(self._preview)
        self.edit.installEventFilter(self)
        self._setup_suggestions()

    # ---- suggestions -------------------------------------------------------------------

    def _setup_suggestions(self) -> None:
        self._found = quick_entry.Suggestions(0)
        self._names = QStringListModel(self)
        self.completer = QCompleter(self._names, self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(10)
        self.completer.setWidget(self.edit)  # filtering is ours (quick_entry.suggest)
        popup = cast(QAbstractItemView, self.completer.popup())
        popup.setObjectName("completer")
        # mouse click; the str overload of the signal is not in the PySide6 stubs
        self.completer.activated[str].connect(  # pyright: ignore[reportIndexIssue]
            self.take
        )
        PickWithKeys(popup, self.take)
        popup.installEventFilter(self)  # after PickWithKeys: runs first
        self.edit.textEdited.connect(lambda _text: self.suggest())

    def suggest(self) -> list[str]:
        """Show what fits at the cursor; returns the labels offered."""
        cid = self.s.company_id
        self._found = quick_entry.suggest(
            self.edit.text(),
            self.edit.cursorPosition(),
            self.s.catalog,
            list_templates(self.s.conn, cid),
            lambda account, pos: recent_subconto(self.s.conn, cid, account, pos),
        )
        labels = [i.label for i in self._found.items]
        popup = cast(QAbstractItemView, self.completer.popup())
        if not labels:
            popup.hide()
            return []
        self._names.setStringList(labels)
        # the list opens under the word being typed
        rect = self.edit.cursorRect()
        rect.moveLeft(
            max(
                0,
                rect.left()
                - self.edit.fontMetrics().horizontalAdvance(
                    self.edit.text()[self._found.start : self.edit.cursorPosition()]
                ),
            )
        )
        rect.setWidth(380)
        self.completer.complete(rect)
        fit_popup(popup, len(labels), self.completer.maxVisibleItems())
        if self._found.typed:  # Enter takes the best match
            popup.setCurrentIndex(self._names.index(0))
        else:  # nothing chosen: Enter posts (an arrow key picks from the list)
            popup.setCurrentIndex(QModelIndex())
        return labels

    def take(self, label: str) -> None:
        """Put the chosen item in place of the word being typed, then offer what is next."""
        item = next((i for i in self._found.items if i.label == label), None)
        if item is None:
            return
        cast(QAbstractItemView, self.completer.popup()).hide()
        text, cursor = self.edit.text(), self.edit.cursorPosition()
        start = min(self._found.start, cursor)
        self.edit.setText(text[:start] + item.insert + text[cursor:])
        self.edit.setCursorPosition(start + len(item.insert))
        self.suggest()

    # ---- parsing -----------------------------------------------------------------------

    def _rate(self, currency_id: int, day: date) -> Fraction | None:
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        return rate.per_unit if rate else None

    def parse(self) -> quick_entry.QuickEntry:
        return quick_entry.parse(
            self.edit.text(),
            self.s.catalog,
            list_templates(self.s.conn, self.s.company_id),
            self._rate,
            self.s.working_date,
        )

    def _preview(self, text: str) -> None:
        self.help.setVisible(bool(text.strip()))
        if not text.strip():
            self.preview.hide()
            return
        try:
            entry = self.parse()
        except LedgerError as e:  # still being typed: a quiet hint, red only on Enter
            self._show(str(e), error=False)
            return
        lines = quick_entry.describe(entry, self.s.catalog)
        day = entry.doc_date or self.s.working_date
        head = f"{day:%d.%m.%Y}" + (f"   ·   {entry.memo}" if entry.memo else "")
        notes = []
        if entry.missing:
            notes.append(tr("не заполнено: {what}", what="; ".join(entry.missing)))
        if entry.new_values:
            names = ", ".join(
                f"{self.s.catalog.kinds[v.kind_id]}: {v.name}" for v in entry.new_values
            )
            notes.append(tr("будет добавлено: {names}", names=names))
        self._show("\n".join([head, lines, *notes]), error=False)

    def _show(self, text: str, error: bool) -> None:
        self.preview.setObjectName("error" if error else "secondary")
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
        self.preview.setText(text)
        self.preview.show()

    # ---- actions -----------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() != event.Type.KeyPress:
            return super().eventFilter(obj, event)
        key, mods = event.key(), event.modifiers()
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and obj is self.completer.popup() and not obj.currentIndex().isValid():
            obj.hide()  # the list is open, nothing chosen in it: Enter is the line's
            obj = self.edit
        if obj is self.edit:
            if enter:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    self.to_form()
                else:
                    self.submit(post=not mods & Qt.KeyboardModifier.ShiftModifier)
                return True
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.history:
                step = 1 if key == Qt.Key.Key_Up else -1
                self._back = max(0, min(len(self.history), self._back + step))
                self.edit.setText(self.history[-self._back] if self._back else "")
                return True
            if key == Qt.Key.Key_Escape and self.edit.text():
                self.edit.clear()
                return True
        return super().eventFilter(obj, event)

    def submit(self, post: bool = True) -> int | None:
        """Post (or save as a draft) the typed document; returns its id."""
        text = self.edit.text()
        if not text.strip():
            return None
        led, cid = self.s.ledger, self.s.company_id
        try:
            entry = self.parse()
            with transaction(self.s.conn):
                self._add_new_values(entry)
                inputs = [self._input(n, ln) for n, ln in enumerate(entry.lines, start=1)]
                day = entry.doc_date or self.s.working_date
                create = led.post_new if post else led.create_draft
                doc_id = create(cid, day, inputs, entry.memo)
        except LedgerError as e:
            self.s.catalog.reload()  # elements added in the rolled back transaction
            self._show(str(e), error=True)
            return None
        if entry.new_values:
            self.s.catalog.reload()
        number = load_document(self.s.conn, cid, doc_id).number
        self.s.notify(tr("Документ №{n} проведён" if post else "Документ №{n} сохранён", n=number))
        self.history.append(text)
        self._back = 0
        self.edit.clear()
        cast(QAbstractItemView, self.completer.popup()).hide()
        self.posted.emit(doc_id)
        return doc_id

    def to_form(self) -> None:
        """Open what was typed in the document form, to finish it there."""
        if not self.edit.text().strip():
            return
        try:
            entry = self.parse()
        except LedgerError as e:
            self._show(str(e), error=True)
            return
        postings = [
            PostingData(  # what is still missing stays empty in the form
                ln.debit,  # type: ignore[arg-type]
                ln.credit,  # type: ignore[arg-type]
                ln.amount,  # type: ignore[arg-type]
                pad_subconto(ln.debit_sc),
                pad_subconto(ln.credit_sc),
                ln.memo,
                ln.currency_id,
                ln.currency_amount,
                ln.invoice,
            )
            for ln in entry.lines
        ]
        doc = DocumentData(0, 0, "", entry.memo, "common", "draft", None, None, postings=postings)
        self.history.append(self.edit.text())
        self.edit.clear()
        self.open_form.emit(doc)

    def _add_new_values(self, entry: quick_entry.QuickEntry) -> None:
        for new in entry.new_values:  # a new counterparty comes before its new contract
            owner = new.owner.id if isinstance(new.owner, quick_entry.NewValue) else new.owner
            value_id = self.s.ledger.add_subconto_value(
                self.s.company_id, new.kind_id, new.name, owner_id=owner
            )
            new.id = value_id
            self.s.catalog.add_value(value_id, new.kind_id, new.name, owner_id=owner)
            for index, side, pos in new.cells:
                getattr(entry.lines[index], f"{side}_sc")[pos] = value_id

    @staticmethod
    def _input(n: int, ln: quick_entry.QuickLine) -> PostingInput:
        if ln.debit is None or ln.credit is None:
            raise LedgerError(
                tr("строка {n}: в шаблоне не указан счёт — Ctrl+Enter откроет форму", n=n)
            )
        if ln.amount is None:
            raise LedgerError(tr("строка {n}: не указана сумма", n=n))
        return PostingInput(
            ln.debit,
            ln.credit,
            from_minor(ln.amount),
            tuple(ln.debit_sc),
            tuple(ln.credit_sc),
            ln.memo,
            ln.currency_id,
            None if ln.currency_amount is None else from_minor(ln.currency_amount),
            ln.invoice,
        )
