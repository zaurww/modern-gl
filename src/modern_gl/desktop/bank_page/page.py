"""«Банк / Bank» (D47, D78) on three levels, a click or Enter going down and Esc (or
Backspace) up: the bank accounts and cards by group with what is left to check; the
statements of one account for a period, a day or a period each — or all its lines of the
period; one statement — its lines and its balance against the bank's."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import (
    ACCOUNT_KINDS,
    IN,
    OUT,
    BankAccount,
    BankPlace,
    BankStatement,
    Statement,
    StatementLine,
    bank_accounts,
    bank_statements,
    statement,
)
from modern_gl.desktop.bank_page.actions import (
    ACCOUNTS,
    DAYS,
    JOURNAL,
    LINES,
    STATEMENT,
    BankActions,
)
from modern_gl.desktop.bank_page.entry import EntryLine
from modern_gl.desktop.bank_page.levels import (
    GroupRow,
    account_columns,
    account_rows,
    line_columns,
    period_summary,
    period_text,
    statement_columns,
    where,
)
from modern_gl.desktop.bank_page.reconcile import ReconcileBar
from modern_gl.desktop.period_field import PeriodField
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.widgets import (
    EmptyState,
    button,
    caption,
    icon_button,
    ru_date,
    segments,
)
from modern_gl.domain.periods import MONTH, span_period
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class BankData:
    """What a level of the page reads (in the background for a large company, debt 6)."""

    level: str
    accounts: list[BankAccount]
    statements: list[BankStatement]  # of the account open
    lines: Statement | None  # of the statement open, if it is still there
    period: Statement | None  # the account's lines of the period chosen


class BankPage(BankActions):
    key = ("bank",)
    has_period = False

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("Банк"))
        self.level = ACCOUNTS
        self.account_key: tuple[int, int | None] | None = None
        self.period: tuple[str, str] | None = None
        self.accounts: list[BankAccount] = []
        self.statements: list[BankStatement] = []
        self._amount_mode: str | None = None
        self._start_entry = False  # the cursor to the entry line once the statement is shown
        self.view = DAYS
        self._build_actions()
        self._build_crumbs()
        self._build_bar()
        self.entry = EntryLine(session)
        self.entry.saved.connect(self.refresh)
        self.entry.expand.connect(self.new_bank_operation.emit)
        self.reconcile = ReconcileBar()
        self.reconcile.entered.connect(self._bank_closing_entered)
        self.portal_sign_in: Callable[..., str | None] | None = None  # tests: a token
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
                "○",
                tr("За этот период выписок нет"),
                tr("Другой период — ‹ › у поля периода; «+ Выписка» — следующий рабочий день."),
            ),
            STATEMENT: EmptyState(
                "○", tr("В выписке нет строк"), tr("«+ Приход денег» или «+ Расход денег».")
            ),
        }
        for empty in self.empty_states.values():
            self.stack.addWidget(empty)
        bind(self.table, "delete", self.delete_selected)  # the marked lines
        # an account or a statement opens with one click: the lists are the way in
        self.table.clicked.connect(self._clicked)
        bind(self, "up", self.up)
        bind(self, "previous", lambda: self.step(-1))
        bind(self, "next", lambda: self.step(1))
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
        self.previous = icon_button("back", tr("Предыдущая выписка") + " (Alt+←)")
        self.previous.clicked.connect(lambda: self.step(-1))
        self.following = icon_button("forward", tr("Следующая выписка") + " (Alt+→)")
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

    def _build_bar(self) -> None:
        """An account's period and how to see it: statements by day or all the lines."""
        today = self.s.working_date
        self.period_field = PeriodField(span_period(MONTH, today), today)
        self.period_field.changed.connect(self.refresh)
        box, self.view_buttons = segments(
            [(DAYS, N_("По дням")), (LINES, N_("Все операции"))], self._view_chosen
        )
        self.view_buttons[DAYS].setChecked(True)
        self.bar_box = QWidget()
        bar = QHBoxLayout(self.bar_box)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        label = caption(tr("Период"))
        for widget in (label, self.period_field, box):
            bar.addWidget(widget)
        bar.addStretch(1)
        root = self.layout()
        assert isinstance(root, QVBoxLayout)
        root.insertWidget(root.indexOf(self.header) + 1, self.bar_box)

    def _view_chosen(self) -> None:
        self.view = next(k for k, b in self.view_buttons.items() if b.isChecked())
        self.refresh()

    def period_dates(self) -> tuple[str, str]:
        first, last = self.period_field.period()
        return first.isoformat(), last.isoformat()

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
                label = caption(text)
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
        first, last = self.period_dates()
        if level == JOURNAL and self.period and not first <= self.period[0] <= last:
            # the statement left stays in the list: its month (a new one may be past it)
            self.period_field.blockSignals(True)
            self.period_field.set_period(*span_period(MONTH, date.fromisoformat(self.period[0])))
            self.period_field.blockSignals(False)
        self.refresh()

    def open_account(self, key: tuple[int, int | None]) -> None:
        self.account_key, self.period = key, None
        self.go(JOURNAL)

    def open_statement(self, date_from: str, date_to: str) -> None:
        self.period = (date_from, date_to)
        self._start_entry = True
        self.go(STATEMENT)

    def up(self) -> bool:
        """A level up; False at the top (Esc goes on to the window)."""
        if self.level == ACCOUNTS:
            return False
        self.go(JOURNAL if self.level == STATEMENT else ACCOUNTS)
        self.table.setFocus()  # the entry line is hidden: the cursor stays on the page
        return True

    def keyPressEvent(self, event) -> None:
        # Esc nobody inside wanted (an empty entry line, the table): a level up
        if event.key() == Qt.Key.Key_Escape and not event.modifiers() and self.up():
            return
        super().keyPressEvent(event)

    def _clicked(self, index: QModelIndex) -> None:
        row = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, (BankAccount, BankStatement)):
            self.drill(row)

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

    def _bind_open(self) -> None:
        """Enter opens a row of the table only: in the entry line it goes on through it."""
        bind(self.table, "open_row", self._drill_current)

    def activated(self) -> None:
        self.refresh()
        self.focus_table()

    def on_postings_changed(self, doc_id: int) -> None:
        self.refresh()

    def fetch(self, conn: Connection) -> BankData:
        return self.job()(conn)

    def job(self) -> Callable[[Connection], BankData]:
        cid, day = self.s.company_id, self.s.working_date.isoformat()
        level, key, period = self.level, self.account_key, self.period
        chosen = self.period_dates()

        def read(conn: Connection) -> BankData:
            accounts = bank_accounts(conn, cid, day)
            account = next((a for a in accounts if a.place.key == key), None)
            statements = bank_statements(conn, cid, account.place) if account else []
            here = any((s.date_from, s.date_to) == period for s in statements)
            lines = None
            if account and period and level == STATEMENT and here:
                lines = statement(conn, cid, account.place, *period)
            of_period = None
            if account and level == JOURNAL:
                of_period = statement(conn, cid, account.place, *chosen)
            return BankData(level, accounts, statements, lines, of_period)

        return read

    def present(self, data: BankData) -> None:
        self.level, self.accounts, self.statements = data.level, data.accounts, data.statements
        if self.level != ACCOUNTS and self.account is None:
            self.level, self.period = ACCOUNTS, None  # the account is gone
        if self.level == STATEMENT and (self.current is None or data.lines is None):
            self.level = JOURNAL
        if self.level == ACCOUNTS:
            self._build_accounts()
        elif self.level == JOURNAL:
            assert data.period is not None
            self._build_journal(data.period)
        else:
            assert data.lines is not None
            self._build_statement(data.lines)

    def _shown(self) -> None:
        super()._shown()
        if not self.model.rows:
            self.stack.setCurrentWidget(self.empty_states[self.level])
        self._show_level()
        if self._start_entry and self.level == STATEMENT:
            self.entry.start()
        self._start_entry = False

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
        self.footer.setText(
            tr("Щёлкните счёт — откроются его выписки по дням.") if self.accounts else ""
        )

    def _build_journal(self, lines: Statement) -> None:
        account = self.account
        assert account is not None
        self.model.bands = True
        if self.view == LINES:
            self.model.set(line_columns(True), lines.lines, muted=lambda r: r.status != "draft")
        else:
            first, last = self.period_dates()
            shown = [s for s in self.statements if s.date_from <= last and s.date_to >= first]
            self.model.set(statement_columns(), shown)
        kind = dict(ACCOUNT_KINDS)[account.kind]
        self.header.title.setText(account.title)
        self.header.subtitle.setText(f"{where(account)}  ·  {tr(kind)}")
        hint = (
            tr("Двойной щелчок — документ.")
            if self.view == LINES
            else tr("Щёлкните выписку — её строки; внизу выписки впишите остаток из банка.")
        )
        self.footer.setText(f"{period_summary(lines)}\n{hint}")

    def _build_statement(self, lines: Statement) -> None:
        account, s = self.account, self.current
        assert account is not None and s is not None
        self.model.bands = True
        self.model.set(
            line_columns(s.date_from != s.date_to),
            lines.lines,
            muted=lambda r: r.status != "draft",
        )
        self.header.title.setText(period_text(s))
        self.header.subtitle.setText(f"{account.title}  ·  {where(account)}")
        self.reconcile.show_statement(s)
        self.entry.show_for(account.place, s.date_from, s.date_to, self.amount_mode())

    def _show_level(self) -> None:
        level, writes = self.level, not self.s.read_only  # viewing only (D80): nothing new
        self.new_account_button.setVisible(writes and level == ACCOUNTS)
        self.new_statement_button.setVisible(writes and level == JOURNAL)
        self.money_in.setVisible(writes and level != ACCOUNTS)
        self.money_out.setVisible(writes and level != ACCOUNTS)
        self.previous.setVisible(level == STATEMENT)
        self.following.setVisible(level == STATEMENT)
        self.reconcile.setVisible(level == STATEMENT)
        self.entry.setVisible(writes and level == STATEMENT)
        self.reconcile.bank.setReadOnly(not writes)
        self.table.setSelectionMode(  # lines are marked to move or delete them
            QAbstractItemView.SelectionMode.ExtendedSelection
            if self.lines_shown()
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.bar_box.setVisible(level == JOURNAL)
        self.footer.setVisible(level != STATEMENT and bool(self.footer.text()))
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
        elif self.level == JOURNAL and self.view == DAYS and self.period:
            at = next((i for i, s in enumerate(rows) if (s.date_from, s.date_to) == self.period), 0)
        self.table.setCurrentIndex(self.model.index(at, 0) if at >= 0 else QModelIndex())

    def drill(self, row: object) -> None:
        if isinstance(row, BankAccount):
            self.open_account(row.place.key)
        elif isinstance(row, BankStatement):
            self.open_statement(row.date_from, row.date_to)
        elif isinstance(row, StatementLine):
            self.open_document.emit(row.document_id)
