"""The quick entry line above the journal: type a document as text, see how it is
understood, Enter posts it (see application.quick_entry for the syntax).

While typing, a list offers what fits at the cursor — accounts, then the elements of
their subconto (after "26 " the cost items), currencies, templates — so the syntax need
not be remembered: Enter or Tab takes the highlighted item and adds what comes next."""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from typing import cast

from PySide6.QtCore import QCoreApplication, QModelIndex, QStringListModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QInputMethodEvent, QTextCharFormat
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
from modern_gl.application.queries import (
    DocumentData,
    PastPosting,
    PostingData,
    list_templates,
    load_document,
    past_postings,
    recent_subconto,
)
from modern_gl.application.quick_entry.marks import Mark, marks
from modern_gl.desktop.cell_editing import PickWithKeys, fit_popup
from modern_gl.desktop.quick_entry_card import EntryCard
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

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
        self.card = EntryCard()
        self.card.finish.connect(self.to_form)
        lay.addWidget(self.card)
        self.help = QLabel(tr(HELP))
        self.help.setObjectName("tertiary")
        self.help.setFont(fonts().small)
        lay.addWidget(self.help)
        self.preview.hide()
        self.card.hide()
        self.help.hide()
        self.edit.textChanged.connect(self._preview)
        self.edit.installEventFilter(self)
        self._setup_suggestions()

    # ---- suggestions -------------------------------------------------------------------

    def _setup_suggestions(self) -> None:
        self._found = quick_entry.Suggestions(0)
        self._past: list[PastPosting] | None = None  # read once, again after posting
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
            self.past(),
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
        widest = max(self.edit.fontMetrics().horizontalAdvance(t) for t in labels) + 48
        rect.setWidth(min(max(380, widest), self.edit.width()))
        self.completer.complete(rect)
        fit_popup(popup, len(labels), self.completer.maxVisibleItems())
        if self._found.typed:  # Enter takes the best match
            popup.setCurrentIndex(self._names.index(0))
        else:  # nothing chosen: Enter posts (an arrow key picks from the list)
            popup.setCurrentIndex(QModelIndex())
        return labels

    def past(self) -> list[PastPosting]:
        if self._past is None:
            self._past = past_postings(self.s.conn, self.s.company_id)
        return self._past

    def take(self, label: str) -> None:
        """Put the chosen item in place of the word being typed, then offer what is next;
        a posting from the past comes with its amount selected, to type over."""
        item = next((i for i in self._found.items if i.label == label), None)
        if item is None:
            return
        cast(QAbstractItemView, self.completer.popup()).hide()
        text, cursor = self.edit.text(), self.edit.cursorPosition()
        start = min(self._found.start, cursor)
        self.edit.setText(text[:start] + item.insert + text[cursor:])
        if item.select is not None:
            first, last = item.select
            self.edit.setSelection(start + first, last - first)
            return
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
            self.past(),
        )

    def _preview(self, text: str) -> None:
        self.help.setVisible(bool(text.strip()))
        self._paint(text)
        if not text.strip():
            self.preview.hide()
            self.card.hide()
            return
        try:
            entry = self.parse()
        except LedgerError as e:  # still being typed: a quiet hint, red only on Enter
            self._show(str(e), error=False)
            return
        self.preview.hide()
        self.card.show_entry(entry, self.s.catalog, entry.doc_date or self.s.working_date)

    def _paint(self, text: str) -> None:
        """Colour the parts as they are understood (Todoist's Quick Add): accounts and
        elements blue, the amount green, a new element amber, what names nothing
        underlined red — except the word still being typed at the end."""
        templates = list_templates(self.s.conn, self.s.company_id)
        found = marks(text, self.s.catalog, templates, self.s.working_date, self.past())
        typing = len(text.rstrip()) if self.edit.cursorPosition() >= len(text.rstrip()) else -1
        cursor = self.edit.cursorPosition()
        attrs = [
            QInputMethodEvent.Attribute(
                QInputMethodEvent.AttributeType.TextFormat,
                m.start - cursor,
                m.end - m.start,
                _format(m),
            )
            for m in found
            if not (m.kind == "unknown" and m.end == typing)
        ]
        QCoreApplication.sendEvent(self.edit, QInputMethodEvent("", attrs))

    def _show(self, text: str, error: bool) -> None:
        self.card.hide()
        self.preview.setObjectName("error" if error else "secondary")
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)
        self.preview.setText(text)
        self.preview.show()

    # ---- actions -----------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() == event.Type.FocusIn and obj is self.edit:
            self._past = None  # documents may have been posted elsewhere meanwhile
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
            doc_id = quick_entry.save_quick_entry(led, cid, entry, self.s.working_date, post)
        except LedgerError as e:
            self.s.catalog.reload()  # elements added in the rolled back transaction
            self._show(str(e), error=True)
            return None
        if entry.new_values:
            self.s.catalog.reload()
        number = load_document(self.s.conn, cid, doc_id).number
        if post:  # «Undo»: back to a draft
            message = tr("Документ №{n} проведён", n=number)
            self.s.notify_undoable(message, lambda: led.unpost(cid, doc_id))
        else:
            self.s.notify(tr("Документ №{n} сохранён", n=number))
        self.history.append(text)
        self._back = 0
        self._past = None
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


def _format(mark: Mark) -> QTextCharFormat:
    f = QTextCharFormat()
    if mark.kind == "unknown":
        f.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        f.setUnderlineColor(QColor(P.red))
        return f
    text, back = {
        "amount": (P.green, P.green_soft),
        "currency": (P.green, P.green_soft),
        "new": (P.amber, P.amber_soft),
    }.get(mark.kind, (P.accent, P.accent_soft))
    f.setForeground(QColor(text))
    f.setBackground(QColor(back))
    if mark.kind == "amount":
        f.setFontWeight(QFont.Weight.DemiBold)
    return f
