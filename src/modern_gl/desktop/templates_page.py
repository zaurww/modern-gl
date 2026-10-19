"""Entry templates (типовые операции): the list and the editor.

List: Enter or double click — new document from the template, F2 — edit,
Ins — new template, Del — delete. The editor is the postings grid whose amount
column holds formulas: S is the operation amount, L1, L2… other lines.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.ledger import TemplateLine
from modern_gl.application.queries import TemplateData, list_templates, load_template
from modern_gl.desktop.postings import PostingRow, PostingsDelegate, PostingsModel, PostingsTable
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, money
from modern_gl.domain import formula
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

PREVIEW_AMOUNT = 100000  # the editor shows what the lines give for S = 1 000.00


class TemplatesPage(QWidget):
    key = ("templates",)
    use_template = Signal(int)  # template id: new document from it
    edit_template = Signal(object)  # template id, or None for a new one

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)

        self.header = PageHeader(tr("Шаблоны операций"), "")
        add = button(tr("+ Новый шаблон"), "flat", "Ins")
        add.clicked.connect(lambda: self.edit_template.emit(None))
        self.header.add_action(add)
        root.addWidget(self.header)

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda idx: self._use(self._at(idx)))
        self.empty = EmptyState(
            "○",
            tr("Шаблонов пока нет"),
            tr("Откройте документ и нажмите «Сделать шаблоном», или Ins."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)
        hint = QLabel(
            tr(
                "Enter — новый документ по шаблону   ·   F2 — изменить   ·   "
                "Ins — новый   ·   Del — удалить"
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        root.addWidget(hint)

        for keys, fn in (
            ("Return", lambda: self._use(self._current())),
            ("Enter", lambda: self._use(self._current())),
            ("F2", lambda: self._edit(self._current())),
            ("Ins", lambda: self.edit_template.emit(None)),
            ("Del", lambda: self.delete(self._current())),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.refresh()

    def title(self) -> str:
        return tr("Шаблоны")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self, select_id: int | None = None) -> None:
        cat = self.s.catalog
        templates = list_templates(self.s.conn, self.s.company_id)
        self.header.subtitle.setText(tr("{n} шаблонов", n=len(templates)))

        def account(account_id: int | None) -> str:
            return cat.accounts[account_id].short if account_id in cat.accounts else "…"

        def entries(t: TemplateData) -> str:
            return "   ·   ".join(
                f"{account(ln.debit_account_id)} → {account(ln.credit_account_id)}"
                for ln in t.lines
            )

        def amounts(t: TemplateData) -> str:
            return "   ·   ".join(ln.formula or "…" for ln in t.lines)

        self.model.set(
            [
                Column(tr("Название"), lambda t: t.name, width=340),
                Column(tr("Дт → Кт"), entries, width=360),
                Column(tr("Суммы"), amounts),
            ],
            templates,
        )
        hh = self.table.horizontalHeader()
        for i, col in enumerate(self.model.columns):
            if col.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, col.width)
        self.stack.setCurrentWidget(self.table if templates else self.empty)
        row = next((i for i, t in enumerate(templates) if t.id == select_id), 0)
        if templates:
            self.table.setCurrentIndex(self.model.index(row, 0))

    def _at(self, idx) -> TemplateData | None:
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    def _current(self) -> TemplateData | None:
        return self._at(self.table.currentIndex())

    def _use(self, t: TemplateData | None) -> None:
        if t is not None:
            self.use_template.emit(t.id)

    def _edit(self, t: TemplateData | None) -> None:
        if t is not None:
            self.edit_template.emit(t.id)

    def delete(self, t: TemplateData | None) -> None:
        if t is None:
            return
        answer = QMessageBox.question(
            self, tr("Удалить шаблон"), tr("Удалить шаблон «{name}»?", name=t.name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.s.ledger.delete_template(self.s.company_id, t.id)
        self.s.notify(tr("Шаблон «{name}» удалён", name=t.name))
        self.refresh()


class TemplatePage(QWidget):
    """Edit one entry template (or make a new one): name, memo, lines with formulas."""

    saved = Signal(int)  # template id
    close_requested = Signal()
    title_changed = Signal()

    def __init__(self, session: Session, template_id: int | None = None) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.template_id = template_id
        self.dirty = False
        t = load_template(session.conn, session.company_id, template_id) if template_id else None

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)

        self.name = QLineEdit(t.name if t else "")
        self.name.setObjectName("titleEdit")
        self.name.setFont(fonts().title)
        self.name.setPlaceholderText(tr("Название шаблона"))
        root.addWidget(self.name)

        meta = QHBoxLayout()
        caption = QLabel(tr("Содержание документа"))
        caption.setObjectName("secondary")
        meta.addWidget(caption)
        self.memo = QLineEdit(t.memo if t else "")
        self.memo.setPlaceholderText(tr("как у шаблона"))
        meta.addWidget(self.memo, 1)
        root.addLayout(meta)

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
            for ln in (t.lines if t else [])
        ]
        self.model = PostingsModel(session.catalog, rows, formulas=True)
        self.delegate = PostingsDelegate(session.catalog, self)
        self.table = PostingsTable(self.model, self.delegate)
        root.addWidget(self.table, 1)

        self.preview = QLabel()
        self.preview.setObjectName("secondary")
        root.addWidget(self.preview)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        hint = QLabel(
            tr(
                "Сумма: S — сумма операции, L1, L2 — суммы строк. "
                "Например: S,  S*18/118 (НДС внутри суммы),  S-L2.  Пусто — ввести вручную."
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_delete.setVisible(template_id is not None)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить шаблон"), "primary", "Ctrl+S")
        actions.addWidget(self.btn_save)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save())
        self.btn_delete.clicked.connect(self.delete)
        self.delegate.error.connect(self.show_error)
        self.model.changed.connect(self._changed)
        self.name.textEdited.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        for keys, fn in (
            ("Ctrl+S", self.save),
            ("Ins", self._insert_row),
            ("F9", self._duplicate_row),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        del_row = QShortcut(QKeySequence("Del"), self.table)
        del_row.setContext(Qt.ShortcutContext.WidgetShortcut)
        del_row.activated.connect(self._remove_row)
        self._update_preview()
        QTimer.singleShot(0, self.name.setFocus)

    @property
    def key(self):
        return ("template", self.template_id or id(self))

    def title(self) -> str:
        text = self.name.text().strip() or tr("Новый шаблон")
        return text + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def _changed(self, *_) -> None:
        self._update_preview()
        if not self.dirty:
            self.dirty = True
        self.title_changed.emit()

    def _update_preview(self) -> None:
        sources = [r.formula for r in self.model.rows]
        try:
            amounts = formula.compute(sources, PREVIEW_AMOUNT)
        except LedgerError as e:
            self.preview.setText(str(e))
            return
        if not any(amounts):
            self.preview.setText("")
            return
        lines = "   ·   ".join(money(a) if a is not None else "…" for a in amounts)
        self.preview.setText(tr("При сумме {s}:  {lines}", s=money(PREVIEW_AMOUNT), lines=lines))

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()

    def _lines(self) -> list[TemplateLine]:
        return [
            TemplateLine(r.debit, r.credit, r.formula, r.debit_sc, r.credit_sc, r.memo)
            for r in self.model.rows
            if not r.is_empty()
        ]

    def save(self, post: bool = False) -> bool:  # `post`: same call as a document's save
        self.table.setFocus()  # commits an open cell editor
        self.error.hide()
        try:
            self.template_id = self.s.ledger.save_template(
                self.s.company_id,
                self.name.text(),
                self._lines(),
                memo=self.memo.text(),
                template_id=self.template_id,
            )
        except LedgerError as e:
            self.show_error(str(e))
            return False
        self.dirty = False
        self.s.notify(tr("Шаблон «{name}» сохранён", name=self.name.text().strip()))
        self.saved.emit(self.template_id)
        return True

    def delete(self) -> None:
        if self.template_id is None:
            return
        answer = QMessageBox.question(
            self,
            tr("Удалить шаблон"),
            tr("Удалить шаблон «{name}»?", name=self.name.text().strip()),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.s.ledger.delete_template(self.s.company_id, self.template_id)
        self.dirty = False
        self.saved.emit(self.template_id)
        self.close_requested.emit()

    def _insert_row(self) -> None:
        cur = self.table.currentIndex()
        row = self.model.insert_row(cur.row() + 1 if cur.isValid() else None)
        self.table.setCurrentIndex(self.model.index(row, 0))

    def _duplicate_row(self) -> None:
        cur = self.table.currentIndex()
        if cur.isValid():
            row = self.model.duplicate_row(cur.row())
            self.table.setCurrentIndex(self.model.index(row, cur.column()))

    def _remove_row(self) -> None:
        cur = self.table.currentIndex()
        if cur.isValid():
            self.model.remove_row(cur.row())
