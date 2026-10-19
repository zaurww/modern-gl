"""The quick entry line above the journal: type a document as text, see how it is
understood, Enter posts it (see application.quick_entry for the syntax)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from modern_gl.application import quick_entry
from modern_gl.application.common import pad_subconto
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import (
    DocumentData,
    PostingData,
    list_templates,
    load_document,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import SCALE
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

HELP = (
    "Enter — провести   ·   Shift+Enter — черновик   ·   Ctrl+Enter — открыть в форме   ·   "
    "↑ — прошлые строки   ·   «+Имя» — новый элемент справочника"
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
        except LedgerError as e:
            self._show(str(e), error=True)
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
        if obj is self.edit and event.type() == event.Type.KeyPress:
            key, mods = event.key(), event.modifiers()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
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
            )
            for ln in entry.lines
        ]
        doc = DocumentData(0, 0, "", entry.memo, "common", "draft", None, None, postings)
        self.history.append(self.edit.text())
        self.edit.clear()
        self.open_form.emit(doc)

    def _add_new_values(self, entry: quick_entry.QuickEntry) -> None:
        for new in entry.new_values:
            value_id = self.s.ledger.add_subconto_value(self.s.company_id, new.kind_id, new.name)
            self.s.catalog.add_value(value_id, new.kind_id, new.name)
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
            Decimal(ln.amount).scaleb(-SCALE),
            tuple(ln.debit_sc),
            tuple(ln.credit_sc),
            ln.memo,
            ln.currency_id,
            None if ln.currency_amount is None else Decimal(ln.currency_amount).scaleb(-SCALE),
        )
