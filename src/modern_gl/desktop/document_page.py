"""A journal document: title-like memo, date/book meta row, postings grid, total, actions."""

from __future__ import annotations

import re
from datetime import date
from fractions import Fraction

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger import TemplateLine
from modern_gl.application.queries import (
    DocumentData,
    TemplateData,
    last_memo,
    list_templates,
    load_document,
    load_template,
    recent_subconto,
)
from modern_gl.desktop.postings import (
    DT,
    EntryHints,
    PostingRow,
    PostingsDelegate,
    PostingsModel,
    PostingsTable,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    ask_date,
    button,
    date_edit,
    edited_date,
    money,
    ru_date,
    to_qdate,
)
from modern_gl.domain import formula
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

HINT = (
    "Enter — следующее поле   ·   Ins — строка   ·   F9 — копия строки   ·   "
    "Del — удалить строку   ·   # — шаблон   ·   Ctrl+V — вставить из Excel   ·   "
    "Ctrl+S — сохранить   ·   Ctrl+Enter — провести   ·   Ctrl+Shift+Enter — провести и новый"
)


class DocumentPage(QWidget):
    saved = Signal(int)  # document id
    open_document = Signal(int)
    copy_requested = Signal(object)  # DocumentData to prefill a new document
    template_saved = Signal(int)  # entry template made from this document
    close_requested = Signal()
    title_changed = Signal()
    new_requested = Signal()  # posted with Ctrl+Shift+Enter: the next document, please

    def __init__(
        self,
        session: Session,
        doc_id: int | None = None,
        template: DocumentData | None = None,
        entry: TemplateData | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc: DocumentData | None = None
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)

        # Title row: the memo is the document's title, like a task name in Things.
        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = self._title_edit()
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        self.layer = QComboBox()
        for code, name in session.layers:
            self.layer.addItem(name, code)
        self.layer.setFixedWidth(230)
        # A document from an entry template asks for the operation amount once (S);
        # lines with a formula follow it.
        self.amount = QLineEdit()
        self.amount.setFixedWidth(150)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        self.amount_caption = QLabel(tr("Сумма операции"))
        for label, w in ((tr("Дата"), self.date), (tr("Книга"), self.layer)):
            caption = QLabel(label)
            caption.setObjectName("secondary")
            meta.addWidget(caption)
            meta.addWidget(w)
            meta.addSpacing(10)
        self.amount_caption.setObjectName("secondary")
        meta.addWidget(self.amount_caption)
        meta.addWidget(self.amount)
        self.amount_caption.hide()
        self.amount.hide()
        meta.addStretch(1)
        root.addLayout(meta)

        self.model = PostingsModel(session.catalog)
        self.model.rate_for = self._rate_for
        cid = session.company_id
        self.delegate = PostingsDelegate(
            session.catalog,
            self,
            EntryHints(
                recent=lambda account, pos: recent_subconto(session.conn, cid, account, pos),
                memo=lambda dt, ct: last_memo(session.conn, cid, dt, ct),
                templates=lambda: [(t.id, t.name) for t in list_templates(session.conn, cid)],
            ),
        )
        self.table = PostingsTable(self.model, self.delegate)
        root.addWidget(self.table, 1)

        # No rate of the document date: load the Central Bank's rates right from here.
        self.rate_note = QFrame()
        self.rate_note.setObjectName("note")
        note = QHBoxLayout(self.rate_note)
        note.setContentsMargins(14, 6, 6, 6)
        self.rate_text = QLabel()
        self.rate_text.setWordWrap(True)
        note.addWidget(self.rate_text, 1)
        self.btn_rates = button(
            tr("Загрузить курс ЦБА"), "flat", tr("Курсы с cbar.az на дату документа")
        )
        self.btn_rates.clicked.connect(self.load_rates)
        note.addWidget(self.btn_rates)
        self.rate_note.hide()
        root.addWidget(self.rate_note)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        bottom = QHBoxLayout()
        self.hint = QLabel(tr(HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)  # never widens the window
        bottom.addWidget(self.hint, 1)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
        bottom.addWidget(total_caption)
        self.total = QLabel()
        self.total.setFont(fonts().total)
        self.total.setMinimumWidth(130)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.total)
        root.addLayout(bottom)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_reverse = button(tr("Сторно…"), "danger", tr("Создать документ красного сторно"))
        self.btn_unpost = button(
            tr("Отменить проведение"), "flat", tr("Вернуть в черновик, чтобы исправить")
        )
        self.btn_copy = button(tr("Копировать"), "flat", tr("Новый документ на основе этого"))
        self.btn_template = button(
            tr("Сделать шаблоном"), "flat", tr("Сохранить проводки как шаблон операции")
        )
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_reverse)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_copy)
        actions.addWidget(self.btn_template)
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
        self.btn_reverse.clicked.connect(self.reverse)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_copy.clicked.connect(lambda: self.copy_requested.emit(self._as_template()))
        self.btn_template.clicked.connect(self.save_as_template)
        self.amount.textEdited.connect(self._amount_edited)
        self.amount.returnPressed.connect(self._focus_grid)
        self.delegate.error.connect(self.show_error)
        self.delegate.unknown_value.connect(self._offer_new_value)
        # deferred: the cell editor that picked the template has to close first
        self.delegate.template_chosen.connect(
            lambda row, tid: QTimer.singleShot(0, lambda: self.insert_template(row, tid))
        )
        self.memo.returnPressed.connect(self._focus_grid)

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

        if doc_id is not None:
            self.load(doc_id)
        else:
            self._set_new(template)
            if entry is not None:
                self._set_entry(entry)
        self._wire_dirty()

    # ---- building helpers ------------------------------------------------------------

    def _title_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("titleEdit")
        edit.setFont(fonts().title)
        edit.setPlaceholderText(tr("Содержание операции"))
        return edit

    def _shortcut(self, keys: str, fn) -> None:
        sc = QShortcut(QKeySequence(keys), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(fn)

    def _grid_shortcut(self, keys: str, fn, while_editing: bool = False) -> None:
        sc = QShortcut(QKeySequence(keys), self.table)
        sc.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
            if while_editing
            else Qt.ShortcutContext.WidgetShortcut
        )
        sc.activated.connect(fn)

    def _finish_editing(self) -> None:
        """Commit and close an open cell editor, so a row action sees what was typed."""
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _wire_dirty(self) -> None:
        self.model.changed.connect(self._changed)
        self.model.changed.connect(self._update_rate_note)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.layer.currentIndexChanged.connect(self._changed)

    # ---- state -----------------------------------------------------------------------

    @property
    def doc_id(self) -> int | None:
        return self.doc.id if self.doc else None

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

    def _rate_for(self, currency_id: int) -> Fraction | None:
        """Manat per unit of a currency on the document date (the latest one before it)."""
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        return rate.per_unit if rate else None

    def _stale_rates(self) -> list[tuple[str, str | None]]:
        """Currencies of lines on the offered rate that have no rate set for the document
        date itself: (code, date of the rate used or None)."""
        day = edited_date(self.date)
        found: dict[str, str | None] = {}
        for i, r in enumerate(self.model.rows):
            if r.currency_id is None or not r.rate_auto or not self.model.in_currency(i):
                continue
            rate = rate_on(self.s.conn, self.s.company_id, r.currency_id, day)
            if rate is None or rate.rate_date < day.isoformat():
                code = self.s.catalog.currencies[r.currency_id].code
                found[code] = rate.rate_date if rate else None
        return sorted(found.items())

    def _update_rate_note(self) -> None:
        stale = [] if self.model.read_only else self._stale_rates()
        if not stale:
            self.rate_note.hide()
            return
        day = ru_date(edited_date(self.date).isoformat())
        parts = [
            tr("курс {code} от {old}", code=code, old=ru_date(old))
            if old
            else tr("нет курса {code}", code=code)
            for code, old in stale
        ]
        self.rate_text.setText(
            tr("На {date} курс не загружен: {what}", date=day, what=", ".join(parts))
        )
        self.rate_note.show()

    def load_rates(self) -> None:
        """Official rates of the document date from cbar.az; the lines take them."""
        day = edited_date(self.date)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.s.ledger.import_rates(self.s.company_id, day, self.s.fetch_rates(day))
        except LedgerError as e:
            self.show_error(str(e))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.error.hide()
        self.model.refresh_rates()
        self._update_rate_note()
        self.s.notify(
            tr("Курсы ЦБА на {date} загружены: {n}", date=ru_date(day.isoformat()), n=count)
        )

    def _date_changed(self, *_) -> None:
        if not self.model.read_only:
            self.error.hide()
            self.model.refresh_rates()

    def _update_total(self) -> None:
        self.total.setText(money(self.model.total(), blank_zero=False))

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

    def _set_entry(self, entry: TemplateData) -> None:
        """Prefill from an entry template; amounts come from the operation amount."""
        self.memo.setText(entry.memo or entry.name)
        rows = [
            PostingRow(
                ln.debit_account_id,
                list(ln.debit_subconto),
                ln.credit_account_id,
                list(ln.credit_subconto),
                None,
                ln.memo,
                ln.formula,
            )
            for ln in entry.lines
        ]
        self.model.beginResetModel()
        self.model.rows = rows or [PostingRow()]
        self.model.endResetModel()
        self.dirty = True
        asks = formula.uses_amount([ln.formula for ln in entry.lines])
        self.amount_caption.setVisible(asks)
        self.amount.setVisible(asks)
        self._update_total()
        QTimer.singleShot(0, (self.amount if asks else self.table).setFocus)
        if not asks:
            QTimer.singleShot(0, self._focus_grid)

    def _amount_edited(self, text: str) -> None:
        self.error.hide()
        try:
            total = to_minor(text) if text.strip() else None
        except ValueError as e:
            self.show_error(str(e))
            return
        problem = self.model.recalculate(total)
        if problem:
            self.show_error(problem)

    def save_as_template(self) -> None:
        """Make an entry template of these lines: an amount equal to the first line's
        becomes S, others stay as numbers — formulas can be refined in the template."""
        self.table.setFocus()  # commits an open cell editor
        name, ok = QInputDialog.getText(
            self, tr("Новый шаблон"), tr("Название шаблона:"), text=self.memo.text().strip()
        )
        if not ok or not name.strip():
            return
        rows = [r for r in self.model.rows if not r.is_empty()]
        first = next((r.amount for r in rows if r.amount), None)
        lines = [
            TemplateLine(
                r.debit,
                r.credit,
                r.formula
                or (
                    "S"
                    if r.amount and r.amount == first
                    else (format_minor(r.amount).replace(" ", "") if r.amount else "")
                ),
                r.debit_sc,
                r.credit_sc,
                r.memo,
            )
            for r in rows
        ]
        try:
            template_id = self.s.ledger.save_template(
                self.s.company_id, name, lines, memo=self.memo.text()
            )
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.s.notify(tr("Шаблон «{name}» сохранён", name=name.strip()))
        self.template_saved.emit(template_id)

    def load(self, doc_id: int) -> None:
        self.doc = load_document(self.s.conn, self.s.company_id, doc_id)
        d = self.doc
        self.number.setText(f"№{d.number}")
        self.memo.setText(d.memo)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        self._select_layer(d.layer)
        read_only = d.status == "posted"
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

    def _select_layer(self, code: str) -> None:
        i = self.layer.findData(code)
        if i >= 0:
            self.layer.setCurrentIndex(i)

    def _apply_mode(self, read_only: bool) -> None:
        for w in (self.memo, self.date, self.layer):
            w.setEnabled(not read_only)
        self.memo.setReadOnly(read_only)
        self.btn_save.setVisible(not read_only)
        self.btn_post.setVisible(not read_only)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(
            read_only and self.doc is not None and self.doc.reversal_of is None
        )
        can_reverse = (
            read_only
            and self.doc is not None
            and self.doc.reversal_of is None
            and self.doc.reversed_by is None
        )
        self.btn_reverse.setVisible(can_reverse)
        self.btn_copy.setVisible(self.doc is not None)
        if read_only:
            self.amount.setEnabled(False)
        self.hint.setVisible(not read_only)
        self._update_total()

    # ---- actions ---------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

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

    def insert_template(self, row: int, template_id: int) -> None:
        """ "#template" typed in a Dt cell: the template's lines take that row's place.
        A document that is otherwise empty becomes the template (with its memo)."""
        template = load_template(self.s.conn, self.s.company_id, template_id)
        others = [r for i, r in enumerate(self.model.rows) if i != row and not r.is_empty()]
        if not others:
            self._set_entry(template)
            return
        offset = row  # template formulas refer to their own lines: L1 -> L(row + 1)…

        def shift(text: str) -> str:
            return re.sub(r"[Ll](\d+)", lambda m: f"L{int(m[1]) + offset}", text)

        if self.model.rows[row].is_empty():
            self.model.remove_row(row)
        for i, ln in enumerate(template.lines):
            self.model.insert_row(
                row + i,
                PostingRow(
                    ln.debit_account_id,
                    list(ln.debit_subconto),
                    ln.credit_account_id,
                    list(ln.credit_subconto),
                    None,
                    ln.memo,
                    shift(ln.formula),
                ),
            )
        asks = formula.uses_amount([ln.formula for ln in template.lines])
        self.amount_caption.setVisible(asks)
        self.amount.setVisible(asks)
        if asks:
            self.amount.setFocus()
            self._amount_edited(self.amount.text())
        self.s.notify(tr("Шаблон «{name}» вставлен", name=template.name))

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

    def _focus_grid(self) -> None:
        self.table.setFocus()
        self.table.setCurrentIndex(self.model.index(0, DT))

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

    # ---- clipboard -----------------------------------------------------------------------

    def _shown(self, col: int) -> bool:
        return not self.table.isColumnHidden(col)

    def paste(self, text: str | None = None) -> None:
        """Lines copied from Excel become postings (see desktop.postings)."""
        if self.model.read_only:
            return
        text = QApplication.clipboard().text() if text is None else text
        if not text.strip():
            return
        self.error.hide()
        cur = self.table.currentIndex()
        row, col = (cur.row(), cur.column()) if cur.isValid() else (0, DT)
        result = self.model.paste(text, row, col, self._shown)
        if result.unknown and self._add_unknown(result.unknown):
            result.unknown = []
        problems = result.errors + [
            tr("нет в справочнике «{kind}»: {text}", kind=self.s.catalog.kinds[k], text=t)
            for _, _, k, t in result.unknown
        ]
        if problems:
            more = len(problems) - 6
            self.show_error(
                "\n".join(problems[:6]) + (f"\n{tr('и ещё {n}', n=more)}" if more > 0 else "")
            )
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def _add_unknown(self, unknown: list[tuple[int, int, int, str]]) -> bool:
        """Names pasted that are not in their directories: add them all in one go."""
        names: dict[tuple[int, str], list[tuple[int, int]]] = {}
        for row, col, kind_id, text in unknown:
            names.setdefault((kind_id, text), []).append((row, col))
        listing = "\n".join(
            f"{self.s.catalog.kinds[kind]}: {text}" for kind, text in list(names)[:12]
        )
        answer = QMessageBox.question(
            self,
            tr("Новые элементы справочников"),
            tr("Этих элементов нет в справочниках. Добавить?\n\n{names}", names=listing),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        # one by one: a new contract belongs to the counterparty its line has by then
        created: dict[tuple[int, str, int | None], int] = {}
        for row, col, kind_id, text in unknown:
            key = (kind_id, text, self.model.owner_at(row, col))
            if key not in created:
                created[key] = self._add_value(kind_id, text, key[2])
            self.model.setData(self.model.index(row, col), created[key])
        return True

    def _add_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        return value_id

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Проводки скопированы — их можно вставить в Excel"))

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        QTimer.singleShot(0, lambda: self._create_value(index, kind_id, text))

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        kind = self.s.catalog.kinds[kind_id]
        answer = QMessageBox.question(
            self,
            tr("Новый элемент справочника"),
            tr("«{text}» нет в справочнике «{kind}». Добавить?", text=text, kind=kind),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes or not index.isValid():
            return
        owner = self.model.owner_at(index.row(), index.column())  # a contract of this partner
        value_id = self._add_value(kind_id, text, owner)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
