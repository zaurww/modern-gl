"""A journal document: title-like memo, date/book meta row, postings grid, total, actions."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
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
from modern_gl.application.queries import DocumentData, TemplateData, load_document
from modern_gl.desktop.postings import (
    DT,
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
    "Del — удалить строку   ·   Ctrl+S — сохранить   ·   Ctrl+Enter — провести"
)


class DocumentPage(QWidget):
    saved = Signal(int)  # document id
    open_document = Signal(int)
    copy_requested = Signal(object)  # DocumentData to prefill a new document
    template_saved = Signal(int)  # entry template made from this document
    close_requested = Signal()
    title_changed = Signal()

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
        self.delegate = PostingsDelegate(session.catalog, self)
        self.table = PostingsTable(self.model, self.delegate)
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        bottom = QHBoxLayout()
        self.hint = QLabel(tr(HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
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
        self.memo.returnPressed.connect(self._focus_grid)

        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        # Ins and F9 also work while a cell is being edited (in 1C-style entry an editor
        # is almost always open); Del inside an editor deletes text, so it does not.
        self._grid_shortcut("Ins", self._insert_row, while_editing=True)
        self._grid_shortcut("F9", self._duplicate_row, while_editing=True)
        self._grid_shortcut("Del", self._remove_row)

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
        """Manat per unit of a currency on the document date; tells when there is none."""
        day = self.date.date().toPython()
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        if rate is None:
            code = self.s.catalog.currencies[currency_id].code
            self.show_error(
                tr(
                    "Нет курса {code} на {date}: введите курс в строке или загрузите курсы "
                    "в разделе «Валюты»",
                    code=code,
                    date=ru_date(day.isoformat()),
                )
            )
            return None
        return rate.per_unit

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
        self._apply_mode(read_only=False, status="new")
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
        self._apply_mode(read_only, d.status)
        self.dirty = False
        self._update_total()
        self.title_changed.emit()

    def _select_layer(self, code: str) -> None:
        i = self.layer.findData(code)
        if i >= 0:
            self.layer.setCurrentIndex(i)

    def _apply_mode(self, read_only: bool, status: str) -> None:
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
        doc_date = self.date.date().toPython()
        memo = self.memo.text().strip()
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
        self.s.notify(
            tr("Документ №{n} проведён" if post else "Документ №{n} сохранён", n=self.doc.number)
        )
        self.saved.emit(doc_id)
        return True

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
        value_id = self.s.ledger.add_subconto_value(self.s.company_id, kind_id, text)
        self.s.catalog.add_value(value_id, kind_id, text)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
