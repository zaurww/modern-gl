"""A journal document: title-like memo, date/book meta row, postings grid, total, actions."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.queries import DocumentData, load_document
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
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import transaction

HINT = (
    "Enter — следующее поле   ·   Ins — строка   ·   F9 — копия строки   ·   Del — удалить строку"
)


class DocumentPage(QWidget):
    saved = Signal(int)  # document id
    open_document = Signal(int)
    copy_requested = Signal(object)  # DocumentData to prefill a new document
    close_requested = Signal()
    title_changed = Signal()

    def __init__(
        self, session: Session, doc_id: int | None = None, template: DocumentData | None = None
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
        for label, w in (("Дата", self.date), ("Книга", self.layer)):
            caption = QLabel(label)
            caption.setObjectName("secondary")
            meta.addWidget(caption)
            meta.addWidget(w)
            meta.addSpacing(10)
        meta.addStretch(1)
        root.addLayout(meta)

        self.model = PostingsModel(session.catalog)
        self.delegate = PostingsDelegate(session.catalog, self)
        self.table = PostingsTable(self.model, self.delegate)
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        bottom = QHBoxLayout()
        self.hint = QLabel(HINT)
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        bottom.addWidget(self.hint, 1)
        total_caption = QLabel("Итого")
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
        self.btn_delete = button("Удалить черновик", "danger")
        self.btn_reverse = button("Сторно…", "danger", "Создать документ красного сторно")
        self.btn_copy = button("Копировать", "flat", "Новый документ на основе этого")
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_reverse)
        actions.addWidget(self.btn_copy)
        actions.addStretch(1)
        self.btn_save = button("Сохранить черновик", tooltip="Ctrl+S")
        self.btn_post = button("Провести", "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_reverse.clicked.connect(self.reverse)
        self.btn_copy.clicked.connect(lambda: self.copy_requested.emit(self._as_template()))
        self.delegate.error.connect(self.show_error)
        self.delegate.unknown_value.connect(self._offer_new_value)
        self.memo.returnPressed.connect(self._focus_grid)

        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self._grid_shortcut("Ins", self._insert_row)
        self._grid_shortcut("F9", self._duplicate_row)
        self._grid_shortcut("Del", self._remove_row)

        if doc_id is not None:
            self.load(doc_id)
        else:
            self._set_new(template)
        self._wire_dirty()

    # ---- building helpers ------------------------------------------------------------

    def _title_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("titleEdit")
        edit.setFont(fonts().title)
        edit.setPlaceholderText("Содержание операции")
        return edit

    def _shortcut(self, keys: str, fn) -> None:
        sc = QShortcut(QKeySequence(keys), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(fn)

    def _grid_shortcut(self, keys: str, fn) -> None:
        sc = QShortcut(QKeySequence(keys), self.table)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(fn)

    def _wire_dirty(self) -> None:
        self.model.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.layer.currentIndexChanged.connect(self._changed)

    # ---- state -----------------------------------------------------------------------

    @property
    def doc_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("doc", self.doc_id) if self.doc else ("new", id(self))

    def title(self) -> str:
        name = f"Документ №{self.doc.number}" if self.doc else "Новый документ"
        return name + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def _changed(self, *_):
        self._update_total()
        if not self.dirty and not self.model.read_only:
            self.dirty = True
            self.title_changed.emit()

    def _update_total(self) -> None:
        self.total.setText(money(self.model.total(), blank_zero=False))

    def _set_new(self, template: DocumentData | None) -> None:
        self.number.setText("Новый")
        self.status.set("Новый", "blue")
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
            self.status.set("Черновик", "amber")
        elif d.reversal_of is not None:
            self.status.set("Сторно", "red")
        elif d.reversed_by is not None:
            self.status.set("Сторнирован", "red")
        else:
            self.status.set("Проведён", "green")
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
        self.btn_delete.setVisible(status == "draft")
        can_reverse = (
            read_only
            and self.doc is not None
            and self.doc.reversal_of is None
            and self.doc.reversed_by is None
        )
        self.btn_reverse.setVisible(can_reverse)
        self.btn_copy.setVisible(self.doc is not None)
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
        self.s.notify(f"Документ №{self.doc.number} {'проведён' if post else 'сохранён'}")
        self.saved.emit(doc_id)
        return True

    def delete(self) -> None:
        if self.doc is None or self.doc.status != "draft":
            return
        answer = QMessageBox.question(
            self, "Удалить черновик", f"Удалить черновик №{self.doc.number}?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.s.ledger.delete_draft(self.s.company_id, self.doc.id)
        self.s.notify(f"Черновик №{self.doc.number} удалён")
        self.dirty = False
        self.saved.emit(self.doc.id)
        self.close_requested.emit()

    def reverse(self) -> None:
        if self.doc is None:
            return
        when = ask_date(
            self,
            "Сторно",
            f"Дата документа сторно для №{self.doc.number} от {ru_date(self.doc.doc_date)}:",
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
        cur = self.table.currentIndex()
        row = self.model.insert_row(cur.row() + 1 if cur.isValid() else None)
        idx = self.model.index(row, DT)
        self.table.setCurrentIndex(idx)
        self.table.edit(idx)

    def _duplicate_row(self) -> None:
        cur = self.table.currentIndex()
        if self.model.read_only or not cur.isValid():
            return
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
            "Новый элемент справочника",
            f"«{text}» нет в справочнике «{kind}». Добавить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes or not index.isValid():
            return
        value_id = self.s.ledger.add_subconto_value(self.s.company_id, kind_id, text)
        self.s.catalog.add_value(value_id, kind_id, text)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        self.s.notify(f"Добавлено в «{kind}»: {text}")
