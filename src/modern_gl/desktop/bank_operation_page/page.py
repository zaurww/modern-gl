"""A bank operation (D47, D68): money in or out of one bank account. One row on top, set
before typing — which way, the bank account (one field), the date, the kind; then the
cursor's path — who, the e-qaimə, how much, «Провести». Below — lines: what it paid (an
account, a contract, an e-qaimə) and how much; one line is folded into a summary and its
e-qaimə and amount are typed above."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import replace
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
)

from modern_gl.application.bank import (
    CUSTOMER,
    IN,
    OTHER,
    OUT,
    SUPPLIER,
    BankOperationInput,
    load_bank_operation,
    next_to_check,
)
from modern_gl.application.currencies import missing_rates_text
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.application.queries import load_document
from modern_gl.desktop.bank_operation_page.bank import BankAccountPart
from modern_gl.desktop.bank_operation_page.common import (
    bank_accounts,
    select_data,
)
from modern_gl.desktop.bank_operation_page.counterparty import CounterpartyPart
from modern_gl.desktop.bank_operation_page.folded import FoldedPart
from modern_gl.desktop.bank_operation_page.lines import LinesPart
from modern_gl.desktop.posting_preview import document_postings
from modern_gl.desktop.rate_note import load_day_rates
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.widgets import (
    MenuItem,
    edited_date,
    to_qdate,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr


class BankOperationPage(LinesPart, FoldedPart, CounterpartyPart, BankAccountPart):
    def __init__(
        self,
        session: Session,
        operation_id: int | None = None,
        prefill: BankOperationInput | None = None,
    ) -> None:
        super().__init__(session)
        self._connect()
        self._fill_banks()
        self._fill_counterparties()

        if operation_id is not None:
            self.load(operation_id)
        else:
            self._set_new(prefill)

    def _connect(self) -> None:
        self.bank.unknown.connect(self._add_bank)
        self.bank.added.connect(lambda text: self._add_bank(text, True))
        self.currency.unknown.connect(self._not_listed)
        self.kind.unknown.connect(self._not_listed)
        for box in self.sc:
            box.activated.connect(self._bank_subconto_changed)
        self.btn_rates.clicked.connect(self.load_rates)
        self.counterparty_edit.activated.connect(
            lambda _: self._choose_counterparty(self.counterparty_edit.currentData())
        )
        self.counterparty_edit.unknown.connect(self._add_counterparty)
        self.counterparty_edit.added.connect(lambda text: self._add_counterparty(text, True))
        self.btn_party.clicked.connect(self._take_party)
        self.invoice.activated.connect(self._invoice_chosen)
        self.invoice.textEdited.connect(self._invoice_typed)
        self.amount.textEdited.connect(self._amount_typed)
        self.vat_amount.textEdited.connect(self._changed)
        self.deposit.unknown.connect(self._not_listed)
        self.deposit.activated.connect(self._changed)
        self.btn_add_line.clicked.connect(lambda: self.add_line(focus=True))
        self.btn_unfold.clicked.connect(self.unfold)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        bind(self, "save", lambda: self.save(post=self.posted))
        bind(self, "post", lambda: self.save(post=True))
        bind(self, "insert", self._insert_line)
        bind(self, "fee", self._fee_key)
        bind(self, "duplicate_row", self._duplicate_line)
        bind(self, "remove_line", self._remove_current_line)
        self.postings.bind_key(self)
        self.direction.buttonClicked.connect(self._direction_changed)
        self.account.activated.connect(self._bank_account_changed)
        self.bank.activated.connect(self._bank_chosen)
        self.currency.activated.connect(self._changed)
        self.reference.textEdited.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._refresh_invoices)
        self.date.dateChanged.connect(self._show_balance)
        self.date.dateChanged.connect(self._follow_date)
        self.deposit_date.dateChanged.connect(self._deposit_day_changed)
        self.kind.activated.connect(self._kind_changed)

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("bank_op", self.doc.id) if self.doc else ("new_bank_op", id(self))

    def title(self) -> str:
        if self.doc is None:
            title = tr("Новый приход") if self.direction_value == IN else tr("Новый расход")
        elif self.doc.direction == IN:
            title = tr("Приход №{n}", n=self.doc.number)
        else:
            title = tr("Расход №{n}", n=self.doc.number)
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        """The cursor starts where typing starts: who, else how much."""
        if not self.counterparty_edit.isHidden() and self.counterparty is None:
            self.counterparty_edit.setFocus()
        elif self.line_rows:
            self._amount_of(self.line_rows[0]).setFocus()

    def _set_new(self, prefill: BankOperationInput | None) -> None:
        self._loading = True
        data = prefill or BankOperationInput(
            doc_date=self.s.working_date.isoformat(), direction=OUT, account_id=None
        )
        if prefill is None or (prefill.kind == OTHER and not prefill.lines):
            # the usual ones: paid to a supplier, received from a customer
            data = replace(data, kind=SUPPLIER if data.direction == OUT else CUSTOMER)
        if data.account_id is None:  # the first bank account
            accounts = bank_accounts(self.s)
            first = next((a for a in accounts if a.account_type == "bank"), None)
            if first is not None:
                data = replace(data, account_id=first.id)
        self._fill(data)
        if not self.line_rows:
            self.add_line()
            self._default_lines()
        self.number.setText("")
        self.status.set(tr("Новый"), "blue")
        self._loading = False
        self.dirty = prefill is not None and bool(prefill.lines)
        self._lines_edited = bool(prefill and prefill.lines)
        self._apply_mode()
        self._update()
        QTimer.singleShot(0, self.focus_table)

    def load(self, operation_id: int) -> None:
        self.doc = load_bank_operation(self.s.conn, self.s.company_id, operation_id)
        d = self.doc
        self._unfolded = True  # opened again to check its lines: shown, not «Развернуть»
        self._loading = True
        self._fill(d)
        self._loading = False
        self._lines_edited = True
        self.number.setText(f"№{d.number}")
        closed = load_document(self.s.conn, self.s.company_id, d.document_id).closed
        self.read_only = (d.status == "posted" and closed) or self.s.read_only  # viewing (D80)
        if d.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.dirty = False
        self._apply_mode()
        self._update()
        self.title_changed.emit()

    def _fill(self, d: BankOperationInput) -> None:
        (self.btn_in if d.direction == IN else self.btn_out).setChecked(True)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        if d.account_id is not None:
            select_data(self.account, d.account_id, self.s.catalog.accounts[d.account_id].label)
        else:
            self.account.setCurrentIndex(-1)
        self._bank_account_changed(chosen=d.subconto)
        select_data(self.currency, d.currency_id)
        self.reference.setText(d.reference)
        select_data(self.kind, d.kind)
        self._set_counterparty(d.counterparty_id)
        for row in list(self.line_rows):
            self._remove_line(row)
        for line in d.lines:
            self.add_line().set_line(line)
        self.memo.setText(d.memo)
        self._kind_visibility()

    def _apply_mode(self) -> None:
        ro = self.read_only
        for w in (self.date, self.bank, self.account, self.kind, self.btn_in, self.btn_out):
            w.setEnabled(not ro)
        for box in self.sc:
            box.setEnabled(not ro)
        if ro:
            self.currency.setEnabled(False)
        self.counterparty_edit.setEnabled(not ro)
        self.btn_party.setVisible(not ro)
        for edit in (self.memo, self.reference, self.invoice, self.amount):
            edit.setReadOnly(ro)
        for row in self.line_rows:
            row.set_read_only(ro)
        self.btn_add_line.setVisible(not ro)
        self.keys_hint.setVisible(not ro)
        self._layout_lines()
        self.btn_delete.setVisible(self.doc is not None and not ro)
        self.btn_unpost.setVisible(self.posted and not ro)
        self.btn_gl.setVisible(self.posted)
        self.btn_save.setVisible(not ro and not self.posted)  # Ctrl+S reposts it
        self.btn_post.setVisible(not ro)

    def menu_items(self) -> list[MenuItem]:
        items: list[MenuItem] = []
        if not self.read_only:  # a fee taken with the payment: rare, so here and F6
            items.append((tr("Добавить комиссию банка") + "  (F6)", self.add_fee))
        if self.doc is not None and not self.s.read_only:
            items.append((tr("Копировать"), self._copy))
        return items

    def _copy(self) -> None:
        try:
            data = self.collect()
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return
        self.copy_requested.emit(self.copy_of(data))

    @staticmethod
    def copy_of(data: BankOperationInput) -> BankOperationInput:
        """A new operation like this one (a monthly rent): the statement reference and the
        e-qaimə belong to the original."""
        lines = tuple(replace(line, invoice="") for line in data.lines)
        return replace(data, reference="", lines=lines)

    def keyPressEvent(self, event) -> None:
        key, focused = event.key(), QApplication.focusWidget()
        # Enter a field did not want (it took what was typed): on to the next one
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers()
        if enter and focused is self.btn_post:
            self.btn_post.click()
            return
        if enter:
            self.focusNextChild()
            return
        # ← → on «Приход / Расход»: the other way
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and focused in (self.btn_in, self.btn_out):
            if not self.read_only:
                other = self.btn_in if self.btn_out.isChecked() else self.btn_out
                other.click()
                other.setFocus()
            return
        super().keyPressEvent(event)

    # ---- input and actions -----------------------------------------------------------

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self.error.hide()
        self._update()
        if not self.dirty and not self.read_only:
            self.dirty = True
            self.title_changed.emit()

    def collect(self) -> BankOperationInput:
        lines = tuple(line for row in self.line_rows if (line := row.value()) is not None)
        return BankOperationInput(
            doc_date=edited_date(self.date).isoformat(),
            direction=self.direction_value,
            account_id=self.account.currentData(),
            lines=lines,
            kind=self.kind.currentData() or OTHER,
            subconto=self.bank_subconto(),
            currency_id=self.currency.currentData(),
            counterparty_id=None if self.counterparty_edit.isHidden() else self.counterparty,
            memo=self.memo.text().strip() or self._default_memo(),
            reference=self.reference.text().strip(),
        )

    def _update(self) -> None:
        total = 0
        for row in self.line_rows:
            text = row.amount.text().strip()
            with suppress(ValueError):  # a typo: counted once it is a number
                total += to_minor(text) if text else 0
        self.total.setText(f"{format_minor(total)} {self.currency_code()}")
        self.amount_currency.setText(self.currency_code())
        self._layout_lines()
        self._update_rate_note()
        self.postings.changed()

    def _update_rate_note(self) -> None:
        currency_id = self.currency.currentData()
        shown = [] if self.read_only or self.posted or currency_id is None else [currency_id]
        text = missing_rates_text(self.s.conn, self.s.company_id, shown, edited_date(self.date))
        self.rate_text.setText(text)
        self.rate_note.setVisible(bool(text))

    def load_rates(self) -> None:
        if load_day_rates(self.s, edited_date(self.date), self.show_error):
            self._update()

    def save(self, post: bool) -> bool:
        if self.read_only:
            return False
        new = self.doc is None
        # a draft, or one the import posted unseen: the statement is checked line by line
        checking = self.doc is not None and (self.doc.status == "draft" or not self.doc.checked)
        self.error.hide()
        try:
            data = self.collect()
            saved = self._write(data, post)
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return False
        self.load(saved[0])
        assert self.doc is not None
        numbers = [self.doc.number]
        numbers += [
            load_bank_operation(self.s.conn, self.s.company_id, i).number for i in saved[1:]
        ]
        if len(numbers) == 2:
            first, second = numbers
            message = (
                tr("Операции №{a} и №{b} проведены", a=first, b=second)
                if post
                else tr("Черновики №{a} и №{b} сохранены", a=first, b=second)
            )
        elif post:
            message = tr("Операция №{n} проведена", n=self.doc.number)
        else:
            message = tr("Черновик №{n} сохранён", n=self.doc.number)
        self.s.notify(message)
        self.saved.emit(self.doc.document_id)
        if new and post:  # a statement is typed one operation after another
            self.next_requested.emit(self.next_of(data))
        elif checking and post:  # the next one to check opens
            after = next_to_check(self.s.conn, self.s.company_id, self.doc.id)
            if after is None:
                self.close_requested.emit()  # none left: back to the statement
            else:
                self.draft_requested.emit(after)
        return True

    def _write(self, data: BankOperationInput, post: bool) -> list[int]:
        """Save the operation as typed: the operations written (a new payment with its
        ƏDV part on the deposit, if typed — two)."""
        if self.doc is None:
            data = self._vat_line(data)
            deposit = self._deposit_part(data)
            return self.s.ledger.bank.save_bank_payment(
                self.s.company_id, data, deposit, post=post, checked=post
            )
        return [
            self.s.ledger.bank.save_bank_operation(
                self.s.company_id, data, self.doc.id, post=post, checked=post
            )
        ]

    def postings_preview(self) -> PostingPreview:
        """Posted and not edited — its postings; else what «Провести» would post."""
        saved = [self.doc.id] if self.doc is not None else []
        stored = self.posted and not self.dirty
        write = None if stored else lambda: self._write(self.collect(), post=True)
        return document_postings(self.s, "bank", saved, write)

    @staticmethod
    def next_of(data: BankOperationInput) -> BankOperationInput:
        """The next operation of the statement: the same bank account, day and way."""
        return BankOperationInput(
            doc_date=data.doc_date,
            direction=data.direction,
            account_id=data.account_id,
            subconto=data.subconto,
            currency_id=data.currency_id,
        )

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.s.ledger.bank.unpost_bank_operation(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(self.doc.document_id)

    def delete(self) -> None:
        if self.doc is None:
            return
        question = tr("Удалить операцию №{n}?", n=self.doc.number)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.bank.delete_bank_operation(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.saved.emit(self.doc.document_id)
        self.dirty = False
        self.close_requested.emit()

    def _open_gl(self) -> None:
        if self.doc is not None:
            self.open_gl_document.emit(self.doc.document_id)
