"""«Банк / Bank» (D47, D78) on three levels, Enter going down and Backspace up: the bank
accounts and cards by group with what is left to check; the statements of one account,
a day or a period each; one statement — its lines and its balance against the bank's."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QModelIndex, QSettings, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
)

from modern_gl.application.bank import (
    ACCOUNT_KINDS,
    IN,
    OUT,
    BankAccount,
    BankOperationInput,
    BankPlace,
    BankStatement,
    StatementLine,
    bank_accounts,
    bank_operation_of_document,
    bank_places,
    bank_statements,
    statement,
)
from modern_gl.desktop.bank_page.dialogs import BankAccountDialog, PeriodDialog
from modern_gl.desktop.bank_page.entry import ONE, TWO, EntryLine
from modern_gl.desktop.bank_page.levels import (
    GroupRow,
    account_columns,
    account_rows,
    line_columns,
    period_text,
    statement_columns,
    where,
)
from modern_gl.desktop.bank_page.reconcile import ReconcileBar
from modern_gl.desktop.bank_page.settings import BankSettingsDialog
from modern_gl.desktop.reports_page import ReportPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, button, more_button, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

ACCOUNTS, JOURNAL, STATEMENT = "accounts", "journal", "statement"


def next_workday(day: str) -> str:
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


class BankPage(ReportPage):
    key = ("bank",)
    has_period = False
    new_bank_operation = Signal(object)  # BankOperationInput: what is known already
    new_conversion = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("Банк"))
        self.level = ACCOUNTS
        self.account_key: tuple[int, int | None] | None = None
        self.period: tuple[str, str] | None = None
        self.accounts: list[BankAccount] = []
        self.statements: list[BankStatement] = []
        self._amount_mode: str | None = None
        self._build_actions()
        self._build_crumbs()
        self.entry = EntryLine(session)
        self.entry.saved.connect(self.refresh)
        self.reconcile = ReconcileBar()
        self.reconcile.entered.connect(self._bank_closing_entered)
        root = self.layout()
        assert isinstance(root, QVBoxLayout)
        root.addWidget(self.entry)
        root.addWidget(self.reconcile)
        self.empty_states = {
            ACCOUNTS: EmptyState(
                "○",
                tr("Банковских счетов нет"),
                tr("«+ Новый счёт» — расчётный, валютный счёт или бизнес-карта."),
            ),
            JOURNAL: EmptyState(
                "○", tr("Выписок пока нет"), tr("«+ Выписка» — на следующий рабочий день.")
            ),
            STATEMENT: EmptyState(
                "○", tr("В выписке нет строк"), tr("«+ Приход денег» или «+ Расход денег».")
            ),
        }
        for empty in self.empty_states.values():
            self.stack.addWidget(empty)
        # Enter opens a row of the table only: in the entry line it goes on through it
        for shortcut in self.findChildren(QShortcut):
            if shortcut.key().toString() in ("Return", "Enter"):
                shortcut.setEnabled(False)
        for keys in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(keys), self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self._drill_current)
        for keys, fn in (
            ("Backspace", self.up),
            ("Alt+Up", self.up),
            ("Alt+Left", lambda: self.step(-1)),
            ("Alt+Right", lambda: self.step(1)),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.refresh()

    # ---- building ---------------------------------------------------------------------

    def _build_actions(self) -> None:
        self.new_account_button = button(tr("+ Новый счёт"), "", tr("Банковский счёт или карта"))
        self.new_account_button.clicked.connect(self.new_account)
        self.new_statement_button = button("", "", tr("Выписка на следующий рабочий день"))
        self.new_statement_button.clicked.connect(self.new_statement)
        self.money_in = button(tr("+ Приход денег"), "", tr("Деньги пришли на счёт"))
        self.money_in.clicked.connect(lambda: self.new_operation(IN))
        self.money_out = button(tr("+ Расход денег"), "", tr("Оплата поставщику, налоги…"))
        self.money_out.clicked.connect(lambda: self.new_operation(OUT))
        self.previous = button("←", "more", tr("Предыдущая выписка") + " (Alt+←)")
        self.previous.clicked.connect(lambda: self.step(-1))
        self.following = button("→", "more", tr("Следующая выписка") + " (Alt+→)")
        self.following.clicked.connect(lambda: self.step(1))
        for control in (
            self.previous,
            self.following,
            self.new_account_button,
            self.new_statement_button,
            self.money_in,
            self.money_out,
        ):
            self.header.add_action(control)
        self.header.add_action(more_button(self._more))

    def _more(self) -> list:
        items: list = []
        if self.level == JOURNAL:
            items.append((tr("Выписка за период…"), self.new_period))
        if self.level == STATEMENT:
            items.append((tr("Перенести отмеченные на другой счёт…"), self.move_selected))
            one = self.amount_mode() == ONE
            items.append(
                (
                    tr("Сумма в двух колонках") if one else tr("Сумма одной колонкой ±"),
                    lambda: self.set_amount_mode(TWO if one else ONE),
                )
            )
        if self.level != ACCOUNTS:
            items.append((tr("Реквизиты счёта…"), self.edit_account))
        else:
            items.append((tr("Новый счёт или карта…"), self.new_account))
        return [
            *items,
            None,
            (tr("Конвертация валюты…"), self.new_conversion.emit),
            (tr("Настройки банка…"), self.settings),
        ]

    def _build_crumbs(self) -> None:
        """Where the page is: «Банк › ABB · AZN › 22.10.2026», each step back a click."""
        self.crumbs = QHBoxLayout()
        self.crumbs.setSpacing(2)
        root = self.layout()
        assert isinstance(root, QVBoxLayout)
        root.insertLayout(0, self.crumbs)  # above the title, as a path

    def _show_crumbs(self) -> None:
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        steps = [(tr("Банк"), ACCOUNTS)]
        if self.level != ACCOUNTS and self.account:
            steps.append((self.account.title, JOURNAL))
        if self.level == STATEMENT and self.current:
            steps.append((period_text(self.current), STATEMENT))
        if len(steps) == 1:
            return
        for i, (text, level) in enumerate(steps):
            if i == len(steps) - 1:
                label = QLabel(text)
                label.setObjectName("secondary")
                self.crumbs.addWidget(label)
                continue
            link = button(text, "crumb")
            link.clicked.connect(lambda _=False, lv=level: self.go(lv))
            self.crumbs.addWidget(link)
            separator = QLabel("›")
            separator.setObjectName("tertiary")
            self.crumbs.addWidget(separator)
        self.crumbs.addStretch(1)

    # ---- where the page is ------------------------------------------------------------

    @property
    def account(self) -> BankAccount | None:
        return next((a for a in self.accounts if a.place.key == self.account_key), None)

    @property
    def place(self) -> BankPlace | None:
        account = self.account
        if self.level == ACCOUNTS:  # the account under the cursor
            row = self.table.currentIndex().data(Qt.ItemDataRole.UserRole)
            account = row if isinstance(row, BankAccount) else None
        return account.place if account else None

    @property
    def current(self) -> BankStatement | None:
        if self.period is None:
            return None
        return next((s for s in self.statements if (s.date_from, s.date_to) == self.period), None)

    def go(self, level: str) -> None:
        self.level = level
        self.refresh()

    def open_account(self, key: tuple[int, int | None]) -> None:
        self.account_key, self.period = key, None
        self.go(JOURNAL)

    def open_statement(self, date_from: str, date_to: str) -> None:
        self.period = (date_from, date_to)
        self.go(STATEMENT)
        if self.level == STATEMENT:
            self.entry.start()

    def up(self) -> None:
        if self.level == STATEMENT:
            self.go(JOURNAL)
        elif self.level == JOURNAL:
            self.go(ACCOUNTS)

    def step(self, delta: int) -> None:
        """The statement before or after this one."""
        if self.level != STATEMENT or self.current is None:
            return
        i = self.statements.index(self.current) + delta
        if 0 <= i < len(self.statements):
            self.open_statement(self.statements[i].date_from, self.statements[i].date_to)

    # ---- the table ----------------------------------------------------------------------

    def title(self) -> str:
        return tr("Банк")

    def refresh(self) -> None:
        cid = self.s.company_id
        self.accounts = bank_accounts(self.s.conn, cid, self.s.working_date.isoformat())
        if self.level != ACCOUNTS and self.account is None:
            self.level, self.period = ACCOUNTS, None  # the account is gone
        self.statements = (
            bank_statements(self.s.conn, cid, self.account.place) if self.account else []
        )
        if self.level == STATEMENT and self.current is None:
            self.level = JOURNAL
        super().refresh()
        if not self.model.rows:
            self.stack.setCurrentWidget(self.empty_states[self.level])
        self._show_level()

    def build(self) -> None:
        if self.level == ACCOUNTS:
            self._build_accounts()
        elif self.level == JOURNAL:
            self._build_journal()
        else:
            self._build_statement()

    def _build_accounts(self) -> None:
        self.model.bands = False
        self.model.set(
            account_columns(),
            account_rows(self.accounts),
            section=lambda r: isinstance(r, GroupRow),
            muted=lambda r: isinstance(r, GroupRow) or (isinstance(r, BankAccount) and r.closed),
        )
        self.header.title.setText(tr("Банк"))
        self.header.subtitle.setText(
            tr("Счета и карты · остаток на {day}", day=ru_date(self.s.working_date.isoformat()))
        )

    def _build_journal(self) -> None:
        account = self.account
        assert account is not None
        self.model.bands = True
        self.model.set(statement_columns(), list(reversed(self.statements)))
        kind = dict(ACCOUNT_KINDS)[account.kind]
        self.header.title.setText(account.title)
        self.header.subtitle.setText(f"{where(account)}  ·  {tr(kind)}")

    def _build_statement(self) -> None:
        account, s = self.account, self.current
        assert account is not None and s is not None
        lines = statement(self.s.conn, self.s.company_id, account.place, s.date_from, s.date_to)
        self.model.bands = True
        self.model.set(
            line_columns(s.date_from != s.date_to),
            lines.lines,
            muted=lambda r: r.status == "draft",
        )
        self.header.title.setText(period_text(s))
        self.header.subtitle.setText(f"{account.title}  ·  {where(account)}")
        self.reconcile.show_statement(s)
        self.entry.show_for(account.place, s.date_from, s.date_to, self.amount_mode())

    def _show_level(self) -> None:
        level = self.level
        self.new_account_button.setVisible(level == ACCOUNTS)
        self.new_statement_button.setVisible(level == JOURNAL)
        self.money_in.setVisible(level != ACCOUNTS)
        self.money_out.setVisible(level != ACCOUNTS)
        self.previous.setVisible(level == STATEMENT)
        self.following.setVisible(level == STATEMENT)
        self.reconcile.setVisible(level == STATEMENT)
        self.entry.setVisible(level == STATEMENT)
        self.table.setSelectionMode(  # lines are marked to move them to another account
            QAbstractItemView.SelectionMode.ExtendedSelection
            if level == STATEMENT
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.footer.hide()
        if level == JOURNAL:
            day = ru_date(self._next_day())[:5]
            self.new_statement_button.setText(tr("+ Выписка · {day}", day=day))
        if level == STATEMENT and self.current is not None:
            i = self.statements.index(self.current)
            self.previous.setEnabled(i > 0)
            self.following.setEnabled(i < len(self.statements) - 1)
        self._show_crumbs()
        self._select_where_it_was()

    def _select_where_it_was(self) -> None:
        """The cursor on the account or statement the page came up from."""
        rows = self.model.rows
        at = 0 if rows else -1
        if self.level == ACCOUNTS:
            accounts = [i for i, r in enumerate(rows) if isinstance(r, BankAccount)]
            at = next(
                (i for i in accounts if rows[i].place.key == self.account_key),
                accounts[0] if accounts else -1,
            )
        elif self.level == JOURNAL and self.period:
            at = next((i for i, s in enumerate(rows) if (s.date_from, s.date_to) == self.period), 0)
        self.table.setCurrentIndex(self.model.index(at, 0) if at >= 0 else QModelIndex())

    def drill(self, row: object) -> None:
        if isinstance(row, BankAccount):
            self.open_account(row.place.key)
        elif isinstance(row, BankStatement):
            self.open_statement(row.date_from, row.date_to)
        elif isinstance(row, StatementLine):
            self.open_document.emit(row.document_id)

    # ---- actions --------------------------------------------------------------------

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
            self.s.ledger.add_bank_statement(
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
            self.s.ledger.set_bank_closing(
                self.s.company_id, place.account_id, place.value_id, s.date_from, s.date_to, amount
            )
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.refresh()

    def new_account(self) -> None:
        if BankAccountDialog(self.s, None, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_account(self) -> None:
        if self.account and BankAccountDialog(self.s, self.account, self).exec():
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
            self._amount_mode = ONE if QSettings().value("bank/amounts", TWO) == ONE else TWO
        return self._amount_mode

    def set_amount_mode(self, mode: str) -> None:
        self._amount_mode = mode
        QSettings().setValue("bank/amounts", mode)
        self.refresh()
        self.entry.start()

    def move_selected(self) -> None:
        """The marked lines entered on the wrong account go to another one of its currency,
        into the statement of the same day there."""
        place = self.place
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        docs = [self.model.rows[r].document_id for r in sorted(rows)]
        conn, cid = self.s.conn, self.s.company_id
        operations = [o for d in docs if (o := bank_operation_of_document(conn, cid, d))]
        if place is None or not operations:
            self.s.notify(tr("Отметьте строки банковских операций (Ctrl или Shift + щелчок)"))
            return
        others = [
            p
            for p in bank_places(conn, cid)
            if p.key != place.key and p.currency_id == place.currency_id
        ]
        target = self.choose_place(others)
        if target is None:
            return
        try:
            self.s.ledger.move_bank_operations(cid, operations, target.account_id, target.subconto)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.notify(tr("Перенесено на {name}: {n}", name=target.name, n=len(operations)))
        self.refresh()

    def choose_place(self, places: list[BankPlace]) -> BankPlace | None:
        """The account to move the lines to, from a menu by the table."""
        menu = QMenu(self)
        for place in places:
            menu.addAction(f"{place.account_code}  {place.name}").setData(place)
        chosen = menu.exec(self.table.mapToGlobal(self.table.rect().center()))
        return chosen.data() if chosen is not None else None
