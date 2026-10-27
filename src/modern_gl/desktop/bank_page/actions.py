"""The bank page's actions (D47, D78): its one «⋯» (D86), a new statement or account, the
ƏDV deposit from the portal and against it (D112, D118), statements from the bank's files
(D146), a new operation, the marked lines moved to another account or deleted. `BankPage`
builds the levels and shows them."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QMenu, QMessageBox

from modern_gl.application.bank import (
    BankAccount,
    BankOperationInput,
    BankPlace,
    BankStatement,
    transfer_targets,
)
from modern_gl.application.queries import document_owner
from modern_gl.desktop.bank_page.deposit_reconcile import DepositReconcileDialog
from modern_gl.desktop.bank_page.dialogs import BankAccountDialog, PeriodDialog
from modern_gl.desktop.bank_page.entry import ONE, TWO
from modern_gl.desktop.bank_page.file_dialog import BankFileDialog
from modern_gl.desktop.bank_page.offset_dialog import AdvanceOffsetDialog
from modern_gl.desktop.bank_page.portal import DepositDialog
from modern_gl.desktop.bank_page.settings import BankSettingsDialog
from modern_gl.desktop.preferences import BANK_AMOUNTS, prefs
from modern_gl.desktop.reports_page import ReportPage
from modern_gl.desktop.widgets import MenuItem
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

ACCOUNTS, JOURNAL, STATEMENT = "accounts", "journal", "statement"
DAYS, LINES = "days", "lines"  # an account's statements by day, or all its lines


def next_workday(day: str) -> str:
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


class BankActions(ReportPage):
    """What the bank page does; the page's state and hooks below are `BankPage`'s."""

    new_bank_operation = Signal(object)  # BankOperationInput: what is known already
    new_conversion = Signal()
    level: str
    view: str  # DAYS or LINES, at the account's level
    statements: list[BankStatement]
    portal_sign_in: Callable[..., str | None] | None  # tests: a token
    _amount_mode: str | None
    _start_entry: bool  # the cursor to the entry line once the statement is shown

    @property
    def account(self) -> BankAccount | None:  # BankPage
        raise NotImplementedError

    @property
    def place(self) -> BankPlace | None:  # BankPage
        raise NotImplementedError

    @property
    def current(self) -> BankStatement | None:  # BankPage
        raise NotImplementedError

    def open_statement(self, date_from: str, date_to: str) -> None:  # BankPage
        raise NotImplementedError

    def more_items(self) -> list[MenuItem]:
        """The one «⋯» of the page (D86): the bank's actions, then the report's (to Excel);
        a company open for viewing gets only the report's."""
        if self.s.read_only:
            return super().more_items()
        return [*self._bank_items(), None, *super().more_items()]

    def _bank_items(self) -> list[MenuItem]:
        items: list[MenuItem] = []
        if self.level == JOURNAL:
            items.append((tr("Выписка за период…"), self.new_period))
        if self.lines_shown():
            items.append((tr("Перенести отмеченные на другой счёт…"), self.move_selected))
            items.append((tr("Удалить отмеченные…  Del"), self.delete_selected))
        if self.level == STATEMENT:
            one = self.amount_mode() == ONE
            items.append(
                (
                    tr("Сумма в двух колонках") if one else tr("Сумма одной колонкой ±"),
                    lambda: self.set_amount_mode(TWO if one else ONE),
                )
            )
        place = self.place  # at the list of accounts: the one under the cursor
        if place is not None and place.account_type == "vat_deposit":
            items.append((tr("Загрузить с портала…"), self.load_from_portal))
            items.append((tr("Сверить с порталом…"), self.reconcile_with_portal))
        else:
            items.append((tr("Загрузить выписку из файла…"), self.load_bank_files))
        if self.level != ACCOUNTS:
            items.append((tr("Реквизиты счёта…"), self.edit_account))
        else:
            items.append((tr("Новый счёт или карта…"), self.new_account))
        return [
            *items,
            (tr("Зачесть авансы…"), self.offset_advances),
            None,
            (tr("Конвертация валюты…"), self.new_conversion.emit),
            (tr("Настройки банка…"), self.settings),
        ]

    def _next_day(self) -> str:
        if self.statements:
            return next_workday(self.statements[-1].date_to)
        return self.s.working_date.isoformat()

    def new_statement(self) -> None:
        day = self._next_day()
        self._add_statement(day, day)

    def new_period(self) -> None:
        dialog = PeriodDialog(date.fromisoformat(self._next_day()), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_statement(*dialog.period())

    def _add_statement(self, date_from: str, date_to: str) -> None:
        place = self.place
        if place is None:
            return
        try:
            self.s.ledger.bank.add_bank_statement(
                self.s.company_id, place.account_id, place.value_id, date_from, date_to
            )
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.open_statement(date_from, date_to)

    def _bank_closing_entered(self, amount: int | None) -> None:
        place, s = self.place, self.current
        if place is None or s is None:
            return
        try:
            self.s.ledger.bank.set_bank_closing(
                self.s.company_id, place.account_id, place.value_id, s.date_from, s.date_to, amount
            )
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.refresh()

    def load_from_portal(self) -> None:
        """The ƏDV deposit account from the portal (D112) for a period chosen (D115): what
        became of the operations — in the window, a double click opens a document."""
        place = self.place
        if place is None:
            return
        dialog = DepositDialog(self.s, place, self, self.portal_sign_in)
        dialog.exec()
        if dialog.imported is not None:
            self.refresh()
        if dialog.chosen_document is not None:
            self.open_document.emit(dialog.chosen_document)

    def load_bank_files(self, paths: Sequence[str] | None = None) -> None:
        """The bank's statement files (several at once — each finds its account by the
        IBAN): what became of the lines — in the window, a double click opens a document."""
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, tr("Выписка из файла"), "", tr("Выписки банка (*.xlsx)")
            )
        if not paths:
            return
        dialog = BankFileDialog(self.s, paths, self.place, self)
        dialog.exec()
        if dialog.imported is not None:
            self.refresh()
        if dialog.chosen_document is not None:
            self.open_document.emit(dialog.chosen_document)

    def reconcile_with_portal(self) -> None:
        """The ƏDV deposit account against the portal for a period (D118)."""
        place = self.place
        if place is None:
            return
        dialog = DepositReconcileDialog(self.s, place, self, self.portal_sign_in)
        dialog.exec()
        if dialog.changed:
            self.refresh()
        if dialog.chosen_document is not None:
            self.open_document.emit(dialog.chosen_document)

    def new_account(self) -> None:
        if BankAccountDialog(self.s, None, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_account(self) -> None:
        if self.account and BankAccountDialog(self.s, self.account, self).exec():
            self.refresh()

    def offset_advances(self) -> None:
        day = self.current.date_to if self.current else self.s.working_date.isoformat()
        if AdvanceOffsetDialog(self.s, day, self).exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Авансы зачтены"))
            self.refresh()

    def settings(self) -> None:
        if BankSettingsDialog(self.s, self).exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Настройки банка сохранены"))

    def new_operation(self, direction: str) -> None:
        """A new operation on this account, dated by the statement (its last day) or the
        working date."""
        place = self.place
        day = self.current.date_to if self.current else self.s.working_date.isoformat()
        self.new_bank_operation.emit(
            BankOperationInput(
                doc_date=day,
                direction=direction,
                account_id=place.account_id if place else None,
                subconto=place.subconto if place else (),
                currency_id=place.currency_id if place else None,
            )
        )

    # ---- the statement's lines ---------------------------------------------------------

    def amount_mode(self) -> str:
        if self._amount_mode is None:  # remembered between sessions
            self._amount_mode = ONE if prefs().view(BANK_AMOUNTS, TWO) == ONE else TWO
        return self._amount_mode

    def set_amount_mode(self, mode: str) -> None:
        self._amount_mode = mode
        prefs().set_view(BANK_AMOUNTS, mode)
        self._start_entry = True
        self.refresh()

    def lines_shown(self) -> bool:
        """A statement, or all the lines of the account's period: lines to mark."""
        return self.level == STATEMENT or (self.level == JOURNAL and self.view == LINES)

    def marked(self) -> tuple[list[int], int]:
        """The bank operations of the marked lines (Ctrl or Shift + click), and how many
        marked lines are other documents (a conversion, a journal entry)."""
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        docs = [self.model.rows[r].document_id for r in sorted(rows)]
        owners = [document_owner(self.s.conn, self.s.company_id, d) for d in docs]
        operations = [o.id for o in owners if o is not None and o.module == "bank"]
        return operations, len(docs) - len(operations)

    def move_selected(self) -> None:
        """The marked lines entered on the wrong account go to another one of its currency,
        into the statement of the same day there."""
        place = self.place
        operations, _others = self.marked()
        conn, cid = self.s.conn, self.s.company_id
        if place is None or not operations:
            self.s.notify(tr("Отметьте строки банковских операций (Ctrl или Shift + щелчок)"))
            return
        target = self.choose_place(transfer_targets(conn, cid, place.key, place.currency_id))
        if target is None:
            return
        try:
            self.s.ledger.bank.move_bank_operations(
                cid, operations, target.account_id, target.subconto
            )
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.notify(tr("Перенесено на {name}: {n}", name=target.name, n=len(operations)))
        self.refresh()

    def delete_selected(self) -> None:
        """The marked lines deleted at once — loaded twice or by mistake: all of them or
        none (one in the closed period keeps them all). Other documents among them stay."""
        if self.s.read_only or not self.lines_shown():
            return
        operations, others = self.marked()
        if not operations:
            self.s.notify(tr("Отметьте строки банковских операций (Ctrl или Shift + щелчок)"))
            return
        question = tr("Удалить отмеченные операции: {n}?", n=len(operations))
        if others:
            question += "\n\n" + tr(
                "Других документов среди отмеченных: {n} — они останутся, их удаляют там, "
                "где они сделаны.",
                n=others,
            )
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.bank.delete_bank_operations(self.s.company_id, operations)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Удалить"), tr("Ничего не удалено: {e}", e=str(e)))
            return
        self.s.notify(tr("Удалено операций: {n}", n=len(operations)))
        self.refresh()

    def choose_place(self, places: list[BankPlace]) -> BankPlace | None:
        """The account to move the lines to, from a menu by the table."""
        menu = QMenu(self)
        for place in places:
            menu.addAction(f"{place.account_code}  {place.name}").setData(place)
        chosen = menu.exec(self.table.mapToGlobal(self.table.rect().center()))
        return chosen.data() if chosen is not None else None
