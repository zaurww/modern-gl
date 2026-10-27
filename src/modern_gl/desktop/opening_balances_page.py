"""The company's opening balances, entered like a trial balance: Дебет or Кредит."""

from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction
from functools import partial

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.queries import load_document, opening_document
from modern_gl.desktop.new_cell_value import add_typed_value, offer_new_value
from modern_gl.desktop.opening_postings import CREDIT_AMOUNT, OpeningPostingsModel, OpeningRow
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.postings import (
    AMOUNT,
    CT,
    DT,
    EntryHints,
    PostingsDelegate,
    PostingsTable,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind, legend
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    PageHeader,
    button,
    date_edit,
    edited_date,
    enter_goes_on,
    money,
    ru_date,
    to_qdate,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr, trd

HINT = ("next_field", "previous_field", "insert", "duplicate_row", "delete", "paste_rows", "post")


class OpeningBalancesPage(PageWidget):
    key = ("opening",)
    saved = Signal(int)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc_id: int | None = None
        self.doc_status: str | None = None
        self.dirty = False

        # viewing (D80): the account is not made; none yet — NotFoundError
        self.control_account = session.ledger.opening_account(
            session.company_id, create=not session.read_only
        )
        session.catalog.reload()
        control_code = session.catalog.accounts[self.control_account].short

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)
        self.header = PageHeader(tr("Начальные остатки"), tr("Сальдо до первой операции"))
        self.status = Chip(tr("Новый"), "blue")
        self.header.add_action(self.status)
        root.addWidget(self.header)

        self._build_meta(root)
        self._build_note(root, control_code)
        self._build_table(root)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        self._build_totals(root, control_code)
        self._build_actions(root)
        self._connect()
        self.refresh()

    def _build_meta(self, root: QVBoxLayout) -> None:
        meta = QHBoxLayout()
        caption = QLabel(tr("Остатки на начало дня"))
        caption.setObjectName("secondary")
        meta.addWidget(caption)
        self.date = date_edit(date(self.s.working_date.year, 1, 1))
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addStretch(1)
        root.addLayout(meta)

    def _build_note(self, root: QVBoxLayout, control_code: str) -> None:
        note = QFrame()
        note.setObjectName("note")
        note_lay = QHBoxLayout(note)
        note_lay.setContentsMargins(14, 8, 14, 8)
        explanation = QLabel(
            tr(
                "Перенесите сальдо из ОСВ: счёт, субконто и сумму в колонке «Дебет» или "
                "«Кредит» — можно вставить из Excel. Пока итоги не совпадают, разница "
                "остаётся на счёте {code} и видна в ОСВ.",
                code=control_code,
            )
        )
        explanation.setWordWrap(True)
        note_lay.addWidget(explanation)
        root.addWidget(note)

    def _build_table(self, root: QVBoxLayout) -> None:
        self.model = OpeningPostingsModel(self.s.catalog, self.control_account)
        self.model.rate_for = self._rate_for
        delegate = PostingsDelegate(self.s.catalog, self, EntryHints())
        delegate.error.connect(self.show_error)
        delegate.unknown_value.connect(self._offer_new_value)
        delegate.add_value = partial(add_typed_value, self.s)
        self.table = PostingsTable(self.model, delegate)
        for column in range(CT, CT + 4):  # the counter-account is always the same
            self.table.setColumnHidden(column, True)
        self.table.setColumnWidth(CREDIT_AMOUNT, self.table.columnWidth(AMOUNT))
        bind(self.table, "insert", self._insert_row)
        bind(self.table, "duplicate_row", self._duplicate_row)
        bind(self.table, "delete", self._remove_row)
        bind(self.table, "paste_rows", self.paste)
        bind(self.table, "copy_rows", self.copy)
        root.addWidget(self.table, 1)

    def _build_totals(self, root: QVBoxLayout, control_code: str) -> None:
        totals = QHBoxLayout()
        hint = QLabel(legend(*HINT))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        totals.addWidget(hint, 1)
        self.total_debit = QLabel()
        self.total_credit = QLabel()
        self.difference = QLabel()
        self.difference.setStyleSheet(f"color: {P.red};")
        self.difference.setToolTip(tr("Останется на счёте {code}", code=control_code))
        self.difference_title = QLabel(tr("Разница"))
        for title, value in (
            (QLabel(tr("Дебет")), self.total_debit),
            (QLabel(tr("Кредит")), self.total_credit),
            (self.difference_title, self.difference),
        ):
            title.setObjectName("secondary")
            totals.addWidget(title)
            value.setFont(fonts().total)
            value.setMinimumWidth(120)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            totals.addWidget(value)
        root.addLayout(totals)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        self.btn_difference = button(tr("Разницу — на счёт…"), "flat")
        self.btn_difference.setToolTip(
            tr("Добавить строку, которая закрывает разницу, — останется выбрать счёт")
        )
        actions.addWidget(self.btn_difference)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

    def _connect(self) -> None:
        self.btn_difference.clicked.connect(self.close_difference)
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.model.changed.connect(self._changed)
        bind(self, "save", lambda: self.save(post=False))
        bind(self, "post", lambda: self.save(post=True))

    def title(self) -> str:
        return tr("Начальные остатки")

    def is_dirty(self) -> bool:
        return self.dirty

    def activated(self) -> None:
        self.refresh()
        self.focus_table()

    def focus_table(self) -> None:
        self.table.setFocus()

    def keyPressEvent(self, event) -> None:
        """Enter in the date goes on as Tab does: into the table."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _rate_for(self, currency_id: int) -> Fraction | None:
        day = edited_date(self.date) - timedelta(days=1)  # the day of the GL document
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        return rate.per_unit if rate else None

    def _date_changed(self, *_) -> None:
        if not self.model.read_only:
            self.model.refresh_rates()

    def _changed(self, *_) -> None:
        if not self.model.read_only:
            self.dirty = True
        self._update_totals()

    def _update_totals(self) -> None:
        debit, credit = self.model.totals()
        self.total_debit.setText(money(debit, False))
        self.total_credit.setText(money(credit, False))
        self.difference.setText(money(abs(debit - credit), False))
        differs = debit != credit
        for widget in (self.difference_title, self.difference):
            widget.setVisible(differs)
        self.btn_difference.setVisible(differs and not self.model.read_only)

    def refresh(self) -> None:
        if self.dirty:
            return
        marker = opening_document(self.s.conn, self.s.company_id)
        if marker is None:
            self.doc_id = None
            self.doc_status = None
            self._set_rows([])
            self.status.set(tr("Новый"), "blue")
            self.header.subtitle.setText(tr("Сальдо до первой операции"))
            self._set_read_only(self.s.read_only, posted=False)
            self._update_totals()
            return
        doc = load_document(self.s.conn, self.s.company_id, marker.document_id)
        self.doc_id = doc.id
        self.doc_status = doc.status
        self.date.blockSignals(True)
        self.date.setDate(to_qdate(date.fromisoformat(marker.effective_date)))
        self.date.blockSignals(False)
        self._set_rows([self.model.row_from(p) for p in doc.postings])
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
        read_only = not doc.editable or self.s.read_only  # viewing (D80)
        self._set_read_only(read_only, posted=doc.status == "posted")
        self.dirty = False
        self._update_totals()

    def _set_rows(self, rows: list[OpeningRow]) -> None:
        self.model.beginResetModel()
        self.model.rows = list(rows) or [self.model._blank()]
        self.model.endResetModel()

    def _set_read_only(self, read_only: bool, posted: bool) -> None:
        self.date.setEnabled(not read_only)
        self.model.read_only = read_only
        self.btn_save.setVisible(not read_only and not posted)
        self.btn_post.setVisible(not read_only)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _edit(self, row: int, column: int) -> None:
        index = self.model.index(row, column)
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def _insert_row(self) -> None:
        if self.model.read_only:
            return
        self._finish_editing()
        current = self.table.currentIndex()
        self._edit(self.model.insert_row(current.row() + 1 if current.isValid() else None), DT)

    def _duplicate_row(self) -> None:
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self._finish_editing()
        row = self.model.duplicate_row(current.row())
        self.table.setCurrentIndex(self.model.index(row, current.column()))

    def _remove_row(self) -> None:
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self.model.remove_row(current.row())
        row = min(current.row(), self.model.rowCount() - 1)
        self.table.setCurrentIndex(self.model.index(row, current.column()))

    def close_difference(self) -> None:
        """A line on the side that makes the totals agree; the account is the user's choice
        (the retained earnings account is offered when the chart has exactly one)."""
        if self.model.read_only:
            return
        self._finish_editing()
        debit, credit = self.model.totals()
        if debit == credit:
            return
        retained = [
            a.id for a in self.s.catalog.leaf_accounts if a.account_type == "retained_earnings"
        ]
        line = OpeningRow(
            debit=retained[0] if len(retained) == 1 else None,
            credit=self.control_account,
            amount=abs(debit - credit),
            memo=trd("Разница начальных остатков"),
            on_credit=debit > credit,
        )
        if self.model.rows[-1].is_empty():
            self.model.remove_row(len(self.model.rows) - 1)
        self._edit(self.model.insert_row(None, line), DT)

    def paste(self) -> None:
        if self.model.read_only:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        current = self.table.currentIndex()
        row, column = (current.row(), current.column()) if current.isValid() else (0, DT)
        result = self.model.paste(text, row, column, lambda c: not self.table.isColumnHidden(c))
        problems = result.errors + [
            tr("нет в справочнике «{kind}»: {text}", kind=self.s.catalog.kinds[k], text=t)
            for _, _, k, t in result.unknown
        ]
        if problems:
            self.show_error("\n".join(problems[:6]))
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def copy(self) -> None:
        QApplication.clipboard().setText(
            self.model.copy_text(lambda column: not self.table.isColumnHidden(column))
        )
        self.s.notify(tr("Проводки скопированы — их можно вставить в Excel"))

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        QTimer.singleShot(0, lambda: self._create_value(index, kind_id, text))

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        offer_new_value(self, self.s, self.table, index, kind_id, text, self.model.owner_at)

    def save(self, post: bool) -> bool:
        if self.model.read_only:
            return False
        self._finish_editing()
        self.error.hide()
        try:
            post = post or self.doc_status == "posted"
            effective = edited_date(self.date)
            doc_id = self.s.ledger.save_opening_balances(
                self.s.company_id,
                effective,
                self.model.to_inputs(),
                post=post,
                memo=trd("Начальные остатки на {date}", date=ru_date(effective.isoformat())),
            )
        except (LedgerError, ValueError) as error:
            self.show_error(str(error))
            return False
        debit, credit = self.model.totals()
        self.s.working_date = effective
        self.dirty = False
        self.refresh()
        if debit != credit:
            message = tr(
                "Сохранено. Разница {amount} осталась на счёте {code}",
                amount=money(abs(debit - credit), False),
                code=self.s.catalog.accounts[self.control_account].short,
            )
        elif post:
            message = tr("Начальные остатки проведены")
        else:
            message = tr("Черновик начальных остатков сохранён")
        self.s.notify(message)
        self.saved.emit(doc_id)
        return True
