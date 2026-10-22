"""A journal document: title-like memo, date/book meta row, postings grid, total, actions;
the form, the rates, the templates and the clipboard are in their own modules."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMessageBox,
)

from modern_gl.application.queries import (
    DocumentData,
    TemplateData,
    load_document,
)
from modern_gl.desktop.document_page.clipboard import ClipboardPart
from modern_gl.desktop.document_page.rates import RatesPart
from modern_gl.desktop.document_page.templates import TemplatesPart
from modern_gl.desktop.postings import (
    DT,
    PostingRow,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    MenuItem,
    ask_date,
    edited_date,
    enter_goes_on,
    ru_date,
    to_qdate,
)
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class DocumentPage(RatesPart, TemplatesPart, ClipboardPart):
    def __init__(
        self,
        session: Session,
        doc_id: int | None = None,
        template: DocumentData | None = None,
        entry: TemplateData | None = None,
    ) -> None:
        super().__init__(session)
        self._connect()
        if doc_id is not None:
            self.load(doc_id)
        else:
            self._set_new(template)
            if entry is not None:
                self._set_entry(entry)
        self._wire_dirty()

    def _connect(self) -> None:
        self.btn_rates.clicked.connect(self.load_rates)
        self.btn_source.clicked.connect(self._open_source)
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.amount.textEdited.connect(self._amount_edited)
        self.delegate.error.connect(self.show_error)
        self.delegate.unknown_value.connect(self._offer_new_value)
        self.delegate.add_value = self._add_typed_value
        # deferred: the cell editor that picked the template has to close first
        self.delegate.template_chosen.connect(
            lambda row, tid: QTimer.singleShot(0, lambda: self.insert_template(row, tid))
        )

        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self._shortcut("Ctrl+Shift+Return", self.post_and_new)
        self._shortcut("Ctrl+Shift+Enter", self.post_and_new)
        # Ins and F9 also work while a cell is being edited (in 1C-style entry an editor
        # is almost always open); Del inside an editor deletes text, so it does not.
        self._grid_shortcut("Ins", self._insert_row, while_editing=True)
        self._grid_shortcut("F9", self._duplicate_row, while_editing=True)
        self._grid_shortcut("Del", self._remove_row)
        self._grid_shortcut("Ctrl+V", self.paste)  # inside a cell editor: its own paste
        self._grid_shortcut("Ctrl+C", self.copy)

    def _wire_dirty(self) -> None:
        self.model.changed.connect(self._changed)
        self.model.changed.connect(self._update_rate_note)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.layer.currentIndexChanged.connect(self._changed)

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("doc", self.doc_id) if self.doc else ("new", id(self))

    def title(self) -> str:
        name = tr("Документ №{n}", n=self.doc.number) if self.doc else tr("Новый документ")
        return name + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def _changed(self, *_):
        self._update_total()
        if not self.dirty and not self.model.read_only:
            self.dirty = True
            self.title_changed.emit()

    def _set_new(self, template: DocumentData | None) -> None:
        self.number.setText(tr("Новый"))
        self.status.set(tr("Новый"), "blue")
        if template:
            self.memo.setText(template.memo)
            self._select_layer(template.layer)
            rows = [PostingRow.from_data(p, keep_sign=False) for p in template.postings]
            self.model.beginResetModel()
            self.model.rows = rows or [PostingRow()]
            self.model.endResetModel()
            self.dirty = True
        self._apply_mode(read_only=False)
        QTimer.singleShot(0, self.memo.setFocus)

    def load(self, doc_id: int) -> None:
        self.doc = load_document(self.s.conn, self.s.company_id, doc_id)
        d = self.doc
        self.number.setText(f"№{d.number}")
        self.memo.setText(d.memo)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        self._select_layer(d.layer)
        read_only = not d.editable  # a posted document is edited in place, as in 1C
        self.model.beginResetModel()
        self.model.rows = [PostingRow.from_data(p) for p in d.postings] or [PostingRow()]
        self.model.read_only = read_only
        self.model.endResetModel()
        if d.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        elif d.reversal_of is not None:
            self.status.set(tr("Сторно"), "red")
        elif d.reversed_by is not None:
            self.status.set(tr("Сторнирован"), "red")
        else:
            self.status.set(tr("Проведён"), "green")
        self._apply_mode(read_only)
        self.dirty = False
        self._update_total()
        self._update_rate_note()
        self.title_changed.emit()

    def _apply_mode(self, read_only: bool) -> None:
        for w in (self.memo, self.date, self.layer):
            w.setEnabled(not read_only)
        self.memo.setReadOnly(read_only)
        posted = self.doc is not None and self.doc.status == "posted"
        self.btn_save.setVisible(not read_only and not posted)  # Ctrl+S reposts it
        self.btn_post.setVisible(not read_only)
        source = self.doc.inventory_number if self.doc else None
        self.btn_source.setVisible(source is not None)
        if source is not None:
            self.btn_source.setText(tr("Складской документ №{n}", n=source))
        if read_only:
            self.amount.setEnabled(False)
        self.hint.setVisible(not read_only)
        self._update_total()

    def menu_items(self) -> list[MenuItem]:
        """What "⋯" offers for the document as it is now."""
        doc = self.doc
        if doc is None:  # not saved yet
            return [(tr("Сделать шаблоном"), self.save_as_template)]
        copy = (tr("Копировать"), lambda: self.copy_requested.emit(self._as_template()))
        if doc.conversion_id is not None or doc.bank_operation_id is not None:
            return [copy]  # corrected in the conversion or the bank operation itself
        if doc.inventory_number is not None:
            return [
                (tr("Складской документ №{n}", n=doc.inventory_number), self._open_source),
                copy,
            ]
        posted = doc.status == "posted"
        items: list[MenuItem] = []
        if posted and doc.reversal_of is None:
            items.append((tr("Отменить проведение"), self.unpost))
        items.append(copy)
        items.append((tr("Сделать шаблоном"), self.save_as_template))
        if posted and doc.reversal_of is None and doc.reversed_by is None:
            items += [None, (tr("Сторно…"), self.reverse)]
        return [*items, None, (tr("Удалить"), self.delete)]

    def _open_source(self) -> None:
        if self.doc is not None and self.doc.inventory_document_id is not None:
            self.open_inventory_document.emit(self.doc.inventory_document_id)

    # ---- actions ---------------------------------------------------------------------

    def save(self, post: bool) -> bool:
        if self.model.read_only:
            return False
        self.table.setFocus()  # commits an open cell editor
        self.error.hide()
        doc_date = edited_date(self.date)
        memo = self.memo.text().strip() or next(  # no title: the first posting's memo
            (r.memo.strip() for r in self.model.rows if r.memo.strip()), ""
        )
        layer = self.layer.currentData()
        led, cid = self.s.ledger, self.s.company_id
        try:
            inputs = self.model.to_inputs()
            if self.doc is None:
                if post:
                    doc_id = led.post_new(cid, doc_date, inputs, memo, layer)
                else:
                    doc_id = led.create_draft(cid, doc_date, inputs, memo, layer)
            elif self.doc.status == "posted":  # edited in place: posted again at once
                doc_id = self.doc.id
                led.repost(cid, doc_id, doc_date, inputs, memo, layer)
                post = True
            else:
                doc_id = self.doc.id
                with transaction(self.s.conn):
                    led.update_draft(cid, doc_id, doc_date, inputs, memo, layer)
                    if post:
                        led.post(cid, doc_id)
        except LedgerError as e:
            self.show_error(str(e))
            return False
        self.s.working_date = doc_date
        self.load(doc_id)
        assert self.doc is not None  # load() has just read it
        self.s.notify(
            tr("Документ №{n} проведён" if post else "Документ №{n} сохранён", n=self.doc.number)
        )
        self.saved.emit(doc_id)
        return True

    def post_and_new(self) -> None:
        if self.save(post=True):
            self.new_requested.emit()

    def delete(self) -> None:
        if self.doc is None:
            return
        n = self.doc.number
        question = (
            tr("Удалить черновик №{n}?", n=n)
            if self.doc.status == "draft"
            else tr(
                "Удалить проведённый документ №{n}? Его проводки исчезнут из отчётов, "
                "а полная копия останется в журнале действий.",
                n=n,
            )
        )
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        reversed_id = self.doc.reversal_of
        try:
            self.s.ledger.delete_document(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.s.notify(tr("Документ №{n} удалён", n=n))
        self.dirty = False
        self.saved.emit(reversed_id or self.doc.id)  # a deleted storno revives the original
        self.close_requested.emit()

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.s.ledger.unpost(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.s.notify(
            tr("Проведение документа №{n} отменено — можно исправлять", n=self.doc.number)
        )
        self.saved.emit(self.doc.id)

    def reverse(self) -> None:
        if self.doc is None:
            return
        when = ask_date(
            self,
            tr("Сторно"),
            tr(
                "Дата документа сторно для №{n} от {date}:",
                n=self.doc.number,
                date=ru_date(self.doc.doc_date),
            ),
            self.s.working_date,
        )
        if when is None:
            return
        try:
            new_id = self.s.ledger.reverse(self.s.company_id, self.doc.id, iso_date(when))
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(new_id)
        self.open_document.emit(new_id)

    def _as_template(self) -> DocumentData | None:
        return self.doc

    def keyPressEvent(self, event) -> None:
        """Enter in the title, date, book or operation amount goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _insert_row(self) -> None:
        if self.model.read_only:
            return
        self._finish_editing()
        cur = self.table.currentIndex()
        row = self.model.insert_row(cur.row() + 1 if cur.isValid() else None)
        idx = self.model.index(row, DT)
        self.table.setCurrentIndex(idx)
        self.table.edit(idx)

    def _duplicate_row(self) -> None:
        cur = self.table.currentIndex()
        if self.model.read_only or not cur.isValid():
            return
        self._finish_editing()
        row = self.model.duplicate_row(cur.row())
        self.table.setCurrentIndex(self.model.index(row, cur.column()))

    def _remove_row(self) -> None:
        cur = self.table.currentIndex()
        if self.model.read_only or not cur.isValid():
            return
        self.model.remove_row(cur.row())
        row = min(cur.row(), self.model.rowCount() - 1)
        self.table.setCurrentIndex(self.model.index(row, cur.column()))
