"""The form of an advance report (D-new-advance-reports): who, the day, the lines — what
the money went on, as a postings table — and what it comes to: given before the report,
spent, and what is left (returned to the cash desk) or overspent (paid out to him)."""

from __future__ import annotations

from datetime import date
from functools import partial

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableView, QVBoxLayout

from modern_gl.application.accountable import (
    AccountableModule,
    AdvanceReport,
    AdvanceReportInput,
    accountable_account,
    employee_balance,
    load_advance_report,
)
from modern_gl.desktop.accountable_page.cash import cash_prefill
from modern_gl.desktop.accountable_page.lines import COLUMNS, AdvanceLinesModel
from modern_gl.desktop.grid_editing import EditableRows, GridEditing
from modern_gl.desktop.new_cell_value import add_typed_value, offer_new_value
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.postings import DT, EntryHints, PostingsDelegate, PostingsTable
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind, legend
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    PageHeader,
    button,
    caption,
    date_edit,
    edited_date,
    enter_goes_on,
    money,
    to_qdate,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

HINT = ("next_field", "insert", "duplicate_row", "delete", "post")


class AdvanceReportPage(GridEditing, PageWidget):
    saved = Signal(int)  # the GL document
    new_cash = Signal(object)  # a cash operation to open filled in (BankOperationInput)
    close_requested = Signal()
    title_changed = Signal()

    INSERT_COLUMN = DT
    EDIT_INSERTED = True

    def _grid(self) -> QTableView:
        return self.table

    def _rows(self) -> EditableRows:
        return self.model

    def __init__(
        self, session: Session, report_id: int | None = None, employee_id: int | None = None
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.module = AccountableModule(session.conn, session.ledger.actor, ledger=session.ledger)
        self.account = accountable_account(session.conn, session.company_id)
        self.doc: AdvanceReport | None = None
        self.dirty = False
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)
        self.header = PageHeader(tr("Авансовый отчёт"), "")
        self.status = Chip(tr("Новый"), "blue")
        self.header.add_action(self.status)
        self.header.more(self.menu_items)
        root.addWidget(self.header)
        self._build_bar(root)
        self._build_table(root)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        self._build_totals(root)
        self._connect()
        if report_id is not None:
            self.load(report_id)
        else:
            if employee_id is not None:
                self.employee.setCurrentIndex(self.employee.findData(employee_id))
            self._show_state()

    # ---- building --------------------------------------------------------------------

    def _build_bar(self, root: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(caption(tr("Сотрудник")))
        self.employee = PickBox(tr("Кто отчитывается…"))
        if self.account is not None:
            for v in self.s.catalog.values(self.account.kind_id):
                self.employee.addItem(v.name, v.id)
        self.employee.setFixedWidth(260)
        bar.addWidget(self.employee)
        bar.addSpacing(12)
        bar.addWidget(caption(tr("Дата")))
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        bar.addWidget(self.date)
        bar.addSpacing(12)
        self.memo = QLineEdit()
        self.memo.setPlaceholderText(tr("Содержание — по умолчанию «Авансовый отчёт: сотрудник»"))
        bar.addWidget(self.memo, 1)
        root.addLayout(bar)

    def _build_table(self, root: QVBoxLayout) -> None:
        self.model = AdvanceLinesModel(self.s.catalog, self.account.id if self.account else None)
        delegate = PostingsDelegate(self.s.catalog, self, EntryHints())
        delegate.error.connect(self.show_error)
        delegate.unknown_value.connect(self._offer_new_value)
        delegate.add_value = partial(add_typed_value, self.s)
        self.table = PostingsTable(self.model, delegate)
        for column in range(self.model.columnCount()):
            self.table.setColumnHidden(column, column not in COLUMNS)
        bind(self.table, "insert", self._insert_row)
        bind(self.table, "duplicate_row", self._duplicate_row)
        bind(self.table, "delete", self._remove_row)
        root.addWidget(self.table, 1)

    def _build_totals(self, root: QVBoxLayout) -> None:
        hint = QLabel(legend(*HINT))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        root.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        self.figures: dict[str, tuple[QLabel, QLabel]] = {}
        for key, text in (
            ("given", tr("Выдано до отчёта")),
            ("spent", tr("Израсходовано")),
            ("left", tr("Остаток")),
        ):
            title, value = QLabel(text), QLabel()
            title.setObjectName("secondary")
            value.setFont(fonts().total)
            value.setMinimumWidth(90)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(title)
            row.addWidget(value)
            self.figures[key] = (title, value)
        row.addSpacing(16)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_post)
        root.addLayout(row)

    def _connect(self) -> None:
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.employee.activated.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.model.changed.connect(self._changed)
        bind(self, "save", lambda: self.save(post=False))
        bind(self, "post", lambda: self.save(post=True))

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("advance_report", self.doc.id) if self.doc else ("new_advance_report", id(self))

    @property
    def posted(self) -> bool:
        return self.doc is not None and self.doc.status == "posted"

    @property
    def read_only(self) -> bool:
        return self.s.read_only or self.account is None

    def title(self) -> str:
        name = (
            tr("Авансовый отчёт №{n}", n=self.doc.number)
            if self.doc
            else tr("Новый авансовый отчёт")
        )
        return name + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def activated(self) -> None:
        self._show_figures()

    def focus_table(self) -> None:
        self.table.setFocus()

    def keyPressEvent(self, event) -> None:
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def load(self, report_id: int) -> None:
        doc = load_advance_report(self.s.conn, self.s.company_id, report_id)
        self.doc = doc
        self.employee.setCurrentIndex(self.employee.findData(doc.employee_id))
        self.date.blockSignals(True)
        self.date.setDate(to_qdate(date.fromisoformat(doc.doc_date)))
        self.date.blockSignals(False)
        default = self.module.default_memo(self.s.company_id, doc.employee_id)
        self.memo.setText("" if doc.memo == default else doc.memo)
        self.model.set_lines(list(doc.lines))
        self.dirty = False
        self._show_state()

    def _show_state(self) -> None:
        ro = self.read_only
        if self.doc is None:
            self.status.set(tr("Новый"), "blue")
        elif self.posted:
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self.model.read_only = ro
        for w in (self.employee, self.date, self.memo):
            w.setEnabled(not ro)
        self.btn_save.setVisible(not ro and not self.posted)
        self.btn_post.setVisible(not ro)
        if self.account is None:
            self.show_error(
                tr("нет счёта подотчётных лиц: нужен счёт со справочником «Сотрудники»")
            )
        self._show_figures()
        self.title_changed.emit()

    def _changed(self, *_) -> None:
        if not self.read_only:
            self.dirty = True
            self.title_changed.emit()
        self._show_figures()

    def given(self) -> int:
        """What the employee had before this report: posted ones up to its day."""
        employee = self.employee.currentData()
        if self.account is None or employee is None:
            return 0
        day = edited_date(self.date).isoformat()
        without = self.doc.document_id if self.doc else None
        return employee_balance(
            self.s.conn, self.s.company_id, self.account, employee, day, without=without
        )

    def _show_figures(self) -> None:
        given, spent = self.given(), self.model.spent()
        left = given - spent
        self.figures["given"][1].setText(money(given, False))
        self.figures["spent"][1].setText(money(spent, False))
        title, value = self.figures["left"]
        title.setText(tr("Перерасход — выдать") if left < 0 else tr("Остаток — вернуть в кассу"))
        value.setText(money(abs(left), False))

    # ---- actions ---------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def data(self) -> AdvanceReportInput:
        self.model.check()
        return AdvanceReportInput(
            edited_date(self.date).isoformat(),
            self.employee.currentData(),
            tuple(self.model.lines()),
            self.memo.text().strip(),
        )

    def save(self, post: bool) -> bool:
        if self.read_only:
            return False
        self._finish_editing()
        self.error.hide()
        try:
            saved = self.module.save_advance_report(
                self.s.company_id,
                self.data(),
                self.doc.id if self.doc else None,
                post=post or self.posted,
            )
        except LedgerError as e:
            self.show_error(str(e))
            return False
        self.load(saved)
        assert self.doc is not None
        self.s.notify(
            tr("Проведено: {title}", title=self.title())
            if self.posted
            else tr("Сохранено: {title}", title=self.title())
        )
        self.saved.emit(self.doc.document_id)
        return True

    def menu_items(self) -> list:
        items: list = []
        doc, ro = self.doc, self.read_only
        if doc is not None and self.posted and self.account is not None and not ro:
            left = self.given() - doc.total
            if left:
                text = (
                    tr("Выдать перерасход из кассы…")
                    if left < 0
                    else tr("Принять остаток в кассу…")
                )
                items.append((text, partial(self._cash, abs(left), left < 0)))
            items.append((tr("Отменить проведение"), self.unpost))
        if doc is not None and not ro:
            items.append((tr("Удалить"), self.delete))
        return items

    def _cash(self, amount: int, to_employee: bool) -> None:
        if self.account is None or self.doc is None or self.doc.employee_id is None:
            return
        self.new_cash.emit(
            cash_prefill(
                self.s,
                self.account,
                self.doc.employee_id,
                self.doc.doc_date,
                amount,
                to_employee=to_employee,
            )
        )

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.module.unpost_advance_report(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(self.doc.document_id)

    def delete(self) -> None:
        if self.doc is None:
            return
        question = tr("Удалить авансовый отчёт №{n}?", n=self.doc.number)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.module.delete_advance_report(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.saved.emit(self.doc.document_id)
        self.dirty = False
        self.close_requested.emit()

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        QTimer.singleShot(
            0,
            lambda: offer_new_value(
                self, self.s, self.table, index, kind_id, text, self.model.owner_at
            ),
        )
