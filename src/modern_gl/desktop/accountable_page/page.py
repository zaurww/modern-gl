"""«Подотчётные лица» (D218): every employee money moved for on the
accountable account (71), who owes what; a click — what moved for him in the period:
issued, spent by advance reports, returned. «+ Авансовый отчёт» — the one blue button;
money to and from him goes through «Банк и касса» (`cash`)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from modern_gl.application.accountable import (
    AccountableAccount,
    Person,
    PersonLine,
    PersonStatement,
    accountable_account,
    accountable_people,
    person_statement,
)
from modern_gl.application.document_kinds import document_title
from modern_gl.desktop.accountable_page.cash import cash_prefill
from modern_gl.desktop.reports_page.view import Column, ReportPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.widgets import EmptyState, MenuItem, button, caption, money
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

PEOPLE, PERSON = "people", "person"


@dataclass
class Read:
    account: AccountableAccount | None
    people: list[Person]
    statement: PersonStatement | None


def owes(balance: int) -> int | None:
    return balance if balance > 0 else None


def owed(balance: int) -> int | None:
    return -balance if balance < 0 else None


class AccountablePage(ReportPage):
    key = ("accountable",)
    has_book = False  # the money is the common book's
    choosable_columns = False
    new_report = Signal(object)  # the employee (None: to choose)
    new_cash = Signal(object)  # a cash operation to open filled in

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("Подотчётные лица"))
        self.level = PEOPLE
        self.employee: int | None = None
        self.data = Read(None, [], None)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Подотчётных сумм нет"),
            tr(
                "Выдайте деньги сотруднику в «Банк и касса»: расход из кассы, счёт 71 и "
                "сотрудник. Потом он отчитается авансовым отчётом."
            ),
        )
        self.stack.addWidget(self.empty)
        self.crumbs = QHBoxLayout()
        self.crumbs.setSpacing(2)
        root = self.layout()
        assert isinstance(root, QVBoxLayout)
        root.insertLayout(0, self.crumbs)
        if not session.read_only:
            self.header.primary(
                tr("+ Авансовый отчёт"), lambda: self.new_report.emit(self.employee)
            )
        bind(self, "up", self.up)
        self.refresh()

    def title(self) -> str:
        return tr("Подотчётные лица")

    # ---- reading ---------------------------------------------------------------------

    def job(self):
        level, employee = self.level, self.employee
        first, last = self.params.date_from, self.params.date_to
        return lambda conn: self._read(conn, level, employee, first, last)

    def fetch(self, conn: Connection) -> Read:
        p = self.params
        return self._read(conn, self.level, self.employee, p.date_from, p.date_to)

    def _read(self, conn: Connection, level: str, employee: int | None, first, last) -> Read:
        cid = self.s.company_id
        account = accountable_account(conn, cid)
        if account is None:
            return Read(None, [], None)
        people = accountable_people(conn, cid, account, last)
        st = (
            person_statement(conn, cid, account, employee, first, last)
            if level == PERSON and employee is not None
            else None
        )
        return Read(account, people, st)

    def present(self, data: Read) -> None:
        self.data = data
        if self.level == PERSON and data.statement is not None:
            self._show_person(data.statement)
        else:
            self._show_people(data.people)
        self._show_crumbs()

    def _show_people(self, people: list[Person]) -> None:
        self.model.set(
            [
                Column(tr("Сотрудник"), lambda p: p.name),
                Column(tr("Должен сотрудник"), lambda p: owes(p.balance), money=True),
                Column(tr("Должны сотруднику"), lambda p: owed(p.balance), money=True),
                Column(tr("Последнее движение"), lambda p: ru_date(p.last_day), width=150),
            ],
            people,
            muted=lambda p: p.balance == 0,
        )
        total = sum(p.balance for p in people)
        self.footer.setText(
            tr(
                "На {day} у сотрудников под отчётом: {amount}. Щёлкните сотрудника — его "
                "выдачи, отчёты и возвраты.",
                day=ru_date(self.params.date_to.isoformat()),
                amount=money(total, False),
            )
            if people
            else ""
        )

    def _show_person(self, st: PersonStatement) -> None:
        self.model.set(
            [
                Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
                Column(tr("Документ"), lambda r: document_title(r.kind, r.number), width=220),
                Column(tr("Содержание"), lambda r: r.memo),
                Column(tr("Выдано"), lambda r: r.issued or None, money=True),
                Column(tr("Отчитался, вернул"), lambda r: r.settled or None, money=True),
                Column(tr("Остаток"), lambda r: r.balance, money=True),
            ],
            st.lines,
        )
        self.footer.setText(
            tr(
                "На начало {opening}  ·  выдано {issued}  ·  отчитался и вернул {settled}  ·  "
                "на конец {closing}",
                opening=money(st.opening, False),
                issued=money(sum(r.issued for r in st.lines), False),
                settled=money(sum(r.settled for r in st.lines), False),
                closing=money(st.closing, False),
            )
        )

    # ---- moving ----------------------------------------------------------------------

    def drill(self, row: Any) -> None:
        if isinstance(row, Person):
            self.employee = row.employee_id
            self.level = PERSON
            self.refresh()
        elif isinstance(row, PersonLine):
            self.open_document.emit(row.document_id)

    def up(self) -> None:
        if self.level == PERSON:
            self.level = PEOPLE
            self.refresh()

    def person(self) -> Person | None:
        return next((p for p in self.data.people if p.employee_id == self.employee), None)

    def _show_crumbs(self) -> None:
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        person = self.person()
        if self.level != PERSON or person is None:
            self.header.title.setText(tr("Подотчётные лица"))
            return
        self.header.title.setText(person.name)
        link = button(tr("Подотчётные лица"), "crumb")
        link.clicked.connect(lambda _=False: self.up())
        separator = QLabel("›")
        separator.setObjectName("tertiary")
        self.crumbs.addWidget(link)
        self.crumbs.addWidget(separator)
        self.crumbs.addWidget(caption(person.name))
        self.crumbs.addStretch(1)

    def more_items(self) -> list[MenuItem]:
        items: list[MenuItem] = []
        person, account = self.person(), self.data.account
        if self.level == PERSON and person and account and not self.s.read_only:
            day = self.s.working_date.isoformat()
            items += [
                (
                    tr("Выдать из кассы…"),
                    partial(self._cash, account, person, day, 0, True),
                ),
                (
                    tr("Принять возврат в кассу…"),
                    partial(self._cash, account, person, day, owes(person.balance) or 0, False),
                ),
                None,
            ]
        return [*items, *super().more_items()]

    def _cash(
        self, account: AccountableAccount, person: Person, day: str, amount: int, out: bool
    ) -> None:
        self.new_cash.emit(
            cash_prefill(self.s, account, person.employee_id, day, amount, to_employee=out)
        )
