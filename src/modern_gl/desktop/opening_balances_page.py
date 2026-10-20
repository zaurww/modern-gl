"""A focused, one-sided editor for the company's opening GL balances."""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction
from typing import cast

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.opening_balances import (
    ensure_opening_account,
    opening_document,
    save_opening_document,
)
from modern_gl.application.queries import load_document
from modern_gl.desktop.postings import (
    CT,
    DT,
    EntryHints,
    PostingRow,
    PostingsDelegate,
    PostingsModel,
    PostingsTable,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    PageHeader,
    button,
    date_edit,
    edited_date,
    money,
    ru_date,
    to_qdate,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

HINT = (
    "Enter / Tab — следующее поле   ·   Ins — строка   ·   F9 — копия   ·   "
    "Del — удалить   ·   Ctrl+V — вставить из Excel   ·   Ctrl+Enter — провести"
)


class OpeningPostingsModel(PostingsModel):
    """A normal postings model whose hidden opposite side is always the control account."""

    def __init__(self, *args, side: str, control_account: int, **kwargs) -> None:
        self.opening_side = side
        self.control_account = control_account
        super().__init__(*args, **kwargs)
        if not self.rows or all(r.is_empty() for r in self.rows):
            self.rows = [self._blank()]

    def _blank(self) -> PostingRow:
        return (
            PostingRow(credit=self.control_account)
            if self.opening_side == "debit"
            else PostingRow(debit=self.control_account)
        )

    def _blank_opening(self, row: PostingRow) -> bool:
        account = row.debit if self.opening_side == "debit" else row.credit
        return (
            account is None
            and row.amount is None
            and row.currency_amount is None
            and not row.memo.strip()
            and not row.invoice
        )

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        return super().insert_row(at, row or self._blank())

    def to_inputs(self):
        rows = self.rows
        self.rows = [row for row in rows if not self._blank_opening(row)]
        try:
            return super().to_inputs() if self.rows else []
        finally:
            self.rows = rows


class OpeningBalancesPage(QWidget):
    key = ("opening",)
    saved = Signal(int)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc_id: int | None = None
        self.doc_status: str | None = None
        self.dirty = False

        self.control_account = ensure_opening_account(session.ledger, session.company_id)
        session.catalog.reload()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)
        self.header = PageHeader(
            tr("Начальные остатки"),
            tr("Сальдо до первой операции"),
        )
        self.status = Chip(tr("Новый"), "blue")
        self.header.add_action(self.status)
        root.addWidget(self.header)

        meta = QHBoxLayout()
        caption = QLabel(tr("Остатки на начало дня"))
        caption.setObjectName("secondary")
        meta.addWidget(caption)
        default = date(session.working_date.year, 1, 1)
        self.date = date_edit(default)
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addStretch(1)
        root.addLayout(meta)

        note = QFrame()
        note.setObjectName("note")
        note_lay = QHBoxLayout(note)
        note_lay.setContentsMargins(14, 8, 14, 8)
        explanation = QLabel(
            tr(
                "Внесите дебетовые и кредитовые сальдо по счетам. "
                "Контрагентов, договоры, валюту и E-qaimə укажите в строке. "
                "Итоги дебета и кредита должны совпасть."
            )
        )
        explanation.setWordWrap(True)
        note_lay.addWidget(explanation)
        root.addWidget(note)

        self.debit_model, self.debit_table = self._table("debit")
        self.credit_model, self.credit_table = self._table("credit")
        root.addWidget(self._section_title("Дебетовые остатки", self.debit_model, self.debit_table))
        root.addWidget(self.debit_table, 1)
        root.addWidget(
            self._section_title("Кредитовые остатки", self.credit_model, self.credit_table)
        )
        root.addWidget(self.credit_table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        totals = QHBoxLayout()
        hint = QLabel(tr(HINT))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        totals.addWidget(hint, 1)
        self.total_debit = QLabel()
        self.total_credit = QLabel()
        for title, value in (
            (tr("Дебет"), self.total_debit),
            (tr("Кредит"), self.total_credit),
        ):
            label = QLabel(title)
            label.setObjectName("secondary")
            totals.addWidget(label)
            value.setFont(fonts().total)
            value.setMinimumWidth(120)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            totals.addWidget(value)
        root.addLayout(totals)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        for model in (self.debit_model, self.credit_model):
            model.changed.connect(self._changed)
            model.changed.connect(self._update_totals)
        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self.refresh()

    def _table(self, side: str) -> tuple[OpeningPostingsModel, PostingsTable]:
        model = OpeningPostingsModel(
            self.s.catalog,
            side=side,
            control_account=self.control_account,
            inherit_invoices=False,
        )
        model.rate_for = self._rate_for
        delegate = PostingsDelegate(self.s.catalog, self, EntryHints())
        delegate.error.connect(self.show_error)
        delegate.unknown_value.connect(self._offer_new_value)
        table = PostingsTable(model, delegate)
        hidden = range(CT, CT + 4) if side == "debit" else range(DT, DT + 4)
        for column in hidden:
            table.setColumnHidden(column, True)
        for keys, fn, editing in (
            ("Ins", lambda t=table, m=model: self._insert_row(t, m), True),
            ("F9", lambda t=table, m=model: self._duplicate_row(t, m), True),
            ("Del", lambda t=table, m=model: self._remove_row(t, m), False),
            ("Ctrl+V", lambda t=table, m=model: self.paste(t, m), False),
            ("Ctrl+C", lambda t=table, m=model: self.copy(t, m), False),
        ):
            shortcut = QShortcut(QKeySequence(keys), table)
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
                if editing
                else Qt.ShortcutContext.WidgetShortcut
            )
            shortcut.activated.connect(fn)
        return model, table

    def _section_title(
        self, title: str, model: OpeningPostingsModel, table: PostingsTable
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 0)
        label = QLabel(tr(title))
        label.setFont(fonts().heading)
        layout.addWidget(label)
        layout.addStretch(1)
        add = button(tr("+ Строка"), "flat")
        add.clicked.connect(lambda: self._insert_row(table, model))
        layout.addWidget(add)
        return row

    def title(self) -> str:
        return tr("Начальные остатки")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.debit_table.setFocus()

    def _shortcut(self, keys: str, fn) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(fn)

    def _rate_for(self, currency_id: int) -> Fraction | None:
        rate = rate_on(
            self.s.conn,
            self.s.company_id,
            currency_id,
            edited_date(self.date) - timedelta(days=1),
        )
        return rate.per_unit if rate else None

    def _date_changed(self, *_) -> None:
        for model in (self.debit_model, self.credit_model):
            if not model.read_only:
                model.refresh_rates()

    def _changed(self, *_) -> None:
        if not self.debit_model.read_only:
            self.dirty = True
        self._update_totals()

    def _update_totals(self) -> None:
        debit, credit = self.debit_model.total(), self.credit_model.total()
        self.total_debit.setText(money(debit, False))
        self.total_credit.setText(money(credit, False))
        color = "" if debit == credit else f"color: {P.red};"
        self.total_debit.setStyleSheet(color)
        self.total_credit.setStyleSheet(color)

    def refresh(self) -> None:
        if self.dirty:
            return
        marker = opening_document(self.s.conn, self.s.company_id)
        if marker is None:
            self.doc_id = None
            self.doc_status = None
            self._set_rows([], [])
            self.status.set(tr("Новый"), "blue")
            self.header.subtitle.setText(tr("Сальдо до первой операции"))
            self._set_read_only(False, posted=False)
            self._update_totals()
            return
        doc = load_document(self.s.conn, self.s.company_id, marker.document_id)
        self.doc_id = doc.id
        self.doc_status = doc.status
        self.date.blockSignals(True)
        self.date.setDate(to_qdate(date.fromisoformat(marker.effective_date)))
        self.date.blockSignals(False)
        debit = [
            PostingRow.from_data(p)
            for p in doc.postings
            if p.credit_account_id == self.control_account
        ]
        credit = [
            PostingRow.from_data(p)
            for p in doc.postings
            if p.debit_account_id == self.control_account
        ]
        self._set_rows(debit, credit)
        if doc.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.header.subtitle.setText(
            tr(
                "Документ №{n} · остатки на {date}",
                n=doc.number,
                date=ru_date(marker.effective_date),
            )
        )
        self._set_read_only(not doc.editable, posted=doc.status == "posted")
        self.dirty = False
        self._update_totals()

    def _set_rows(self, debit: list[PostingRow], credit: list[PostingRow]) -> None:
        for model, rows in ((self.debit_model, debit), (self.credit_model, credit)):
            model.beginResetModel()
            model.rows = rows or [model._blank()]
            model.endResetModel()

    def _set_read_only(self, read_only: bool, posted: bool) -> None:
        self.date.setEnabled(not read_only)
        for model in (self.debit_model, self.credit_model):
            model.read_only = read_only
        self.btn_save.setVisible(not read_only and not posted)
        self.btn_post.setVisible(not read_only)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _finish_editing(self, table: PostingsTable) -> None:
        editor = QApplication.focusWidget()
        if table.state() == QAbstractItemView.State.EditingState and editor is not None:
            table.commitData(editor)
            table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _insert_row(self, table: PostingsTable, model: OpeningPostingsModel) -> None:
        if model.read_only:
            return
        self._finish_editing(table)
        current = table.currentIndex()
        row = model.insert_row(current.row() + 1 if current.isValid() else None)
        column = DT if model.opening_side == "debit" else CT
        index = model.index(row, column)
        table.setCurrentIndex(index)
        table.edit(index)

    def _duplicate_row(self, table: PostingsTable, model: OpeningPostingsModel) -> None:
        current = table.currentIndex()
        if model.read_only or not current.isValid():
            return
        self._finish_editing(table)
        row = model.duplicate_row(current.row())
        table.setCurrentIndex(model.index(row, current.column()))

    def _remove_row(self, table: PostingsTable, model: OpeningPostingsModel) -> None:
        current = table.currentIndex()
        if model.read_only or not current.isValid():
            return
        model.remove_row(current.row())
        row = min(current.row(), model.rowCount() - 1)
        table.setCurrentIndex(model.index(row, current.column()))

    def paste(self, table: PostingsTable, model: OpeningPostingsModel) -> None:
        if model.read_only:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        current = table.currentIndex()
        first = DT if model.opening_side == "debit" else CT
        row, column = (current.row(), current.column()) if current.isValid() else (0, first)
        result = model.paste(text, row, column, lambda c: not table.isColumnHidden(c))
        problems = result.errors + [
            tr("нет в справочнике «{kind}»: {text}", kind=self.s.catalog.kinds[k], text=t)
            for _, _, k, t in result.unknown
        ]
        if problems:
            self.show_error("\n".join(problems[:6]))
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def copy(self, table: PostingsTable, model: OpeningPostingsModel) -> None:
        QApplication.clipboard().setText(
            model.copy_text(lambda column: not table.isColumnHidden(column))
        )
        self.s.notify(tr("Проводки скопированы — их можно вставить в Excel"))

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
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
        model = cast(OpeningPostingsModel, index.model())
        owner = model.owner_at(index.row(), index.column())
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner)
        model.setData(model.index(index.row(), index.column()), value_id)
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))

    def save(self, post: bool) -> bool:
        if self.debit_model.read_only:
            return False
        self._finish_editing(self.debit_table)
        self._finish_editing(self.credit_table)
        self.error.hide()
        try:
            post = post or self.doc_status == "posted"
            postings = self.debit_model.to_inputs() + self.credit_model.to_inputs()
            effective = edited_date(self.date)
            memo = tr("Начальные остатки на {date}", date=ru_date(effective.isoformat()))
            doc_id = save_opening_document(
                self.s.ledger,
                self.s.company_id,
                effective,
                postings,
                post=post,
                memo=memo,
            )
        except (LedgerError, ValueError) as error:
            self.show_error(str(error))
            return False
        self.s.working_date = effective
        self.dirty = False
        self.refresh()
        self.s.notify(
            tr("Начальные остатки проведены" if post else "Черновик начальных остатков сохранён")
        )
        self.saved.emit(doc_id)
        return True
