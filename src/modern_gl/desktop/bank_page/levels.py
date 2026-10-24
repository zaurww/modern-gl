"""What the table of the page «Банк» shows on each level (D78): the bank accounts by
group, the statements of one account, the lines of one statement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from modern_gl.application.bank import (
    ACCOUNT_KINDS,
    DIFF,
    KIND_NAMES,
    OK,
    BankAccount,
    BankStatement,
    StatementLine,
)
from modern_gl.desktop.reports_page import Column
from modern_gl.desktop.widgets import ru_date
from modern_gl.domain.dates import date_range
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


@dataclass(frozen=True)
class GroupRow:
    """A group's caption in the list of accounts: «Бизнес-карты»."""

    title: str


def where(account: BankAccount) -> str:
    """ "AZN · 51"."""
    return f"{account.place.currency or 'AZN'}  ·  {account.place.account_code}"


def period_text(s: BankStatement) -> str:
    """ "22.10.2026, чт" or "18.10 — 20.10.2026"."""
    if s.date_from == s.date_to:
        weekday = WEEKDAYS[date.fromisoformat(s.date_from).weekday()]
        return f"{ru_date(s.date_from)}, {tr(weekday)}"
    return date_range(s.date_from, s.date_to)


# ---- the accounts ---------------------------------------------------------------------


def account_rows(accounts: list[BankAccount]) -> list[GroupRow | BankAccount]:
    """Each group with its accounts; closed accounts last, in a group of their own."""
    rows: list[GroupRow | BankAccount] = []
    for kind, name in ACCOUNT_KINDS:
        members = [a for a in accounts if a.kind == kind and not a.closed]
        if members:
            rows += [GroupRow(tr(name)), *members]
    closed = [a for a in accounts if a.closed]
    if closed:
        rows += [GroupRow(tr("Закрытые счета")), *closed]
    return rows


def checks_text(a: BankAccount) -> str:
    """What is left to check against the bank."""
    parts = []
    if a.differences:
        parts.append(tr("расхождение: {n}", n=a.differences))
    if a.unchecked:
        parts.append(tr("не сверено: {n}", n=a.unchecked))
    if not parts and a.last_statement:
        return tr("всё сверено")
    return "  ·  ".join(parts)


def checks_tone(a: BankAccount) -> str | None:
    if a.differences:
        return "red"
    if a.unchecked:
        return "amber"
    return "green" if a.last_statement else None


def account_columns() -> list[Column]:
    def on_account(get):
        return lambda r: get(r) if isinstance(r, BankAccount) else ""

    return [
        Column(tr("Счёт"), lambda r: r.title),
        Column("", on_account(where), width=110, fill=True),  # "AZN · 51" by the name
        Column(
            tr("Последняя выписка"),
            on_account(lambda a: ru_date(a.last_statement) if a.last_statement else ""),
            width=140,
        ),
        Column(
            tr("Сверка с банком"),
            on_account(checks_text),
            tone=lambda r: checks_tone(r) if isinstance(r, BankAccount) else None,
            width=200,
        ),
        Column(
            tr("Остаток"),
            lambda r: r.balance if isinstance(r, BankAccount) else None,
            money=True,
            width=130,
        ),
    ]


# ---- the statements of an account -----------------------------------------------------


def status_text(s: BankStatement) -> str:
    if s.status == OK:
        return tr("сверена")
    if s.status == DIFF:
        return tr("расхождение {amount}", amount=format_minor(s.difference or 0))
    return tr("не сверена")


def status_tone(s: BankStatement) -> str:
    return {OK: "green", DIFF: "red"}.get(s.status, "amber")


def statement_columns() -> list[Column]:
    return [
        Column(tr("Выписка"), period_text, width=200, fill=True),
        Column(tr("На начало"), lambda s: s.opening, money=True, width=120),
        Column(tr("Приход"), lambda s: s.money_in, money=True, width=120),
        Column(tr("Расход"), lambda s: s.money_out, money=True, width=120),
        Column(tr("На конец"), lambda s: s.closing, money=True, width=130),
        Column(tr("Строк"), lambda s: s.lines + s.drafts, right=True, width=70),
        Column(tr("С банком"), status_text, tone=status_tone, width=170),
    ]


# ---- the lines of a statement ---------------------------------------------------------


def line_kind(r: StatementLine) -> str:
    if r.status == "draft":
        return tr("Черновик")
    if r.kind == "conversion":
        return tr("Конвертация валюты")
    if r.kind in KIND_NAMES:
        return tr(KIND_NAMES[r.kind])
    return tr("Журнал")


def line_columns(period: bool) -> list[Column]:
    """A statement of one day needs no date column."""
    columns = [Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100)] if period else []
    return [
        *columns,
        Column(tr("№"), lambda r: r.number, width=60),
        Column(tr("Операция"), line_kind, width=190),
        Column(tr("Контрагент"), lambda r: r.counterparty or r.corr, width=200),
        Column(tr("Назначение"), lambda r: r.memo, fill=True),
        Column(tr("Приход"), lambda r: r.money_in, money=True, width=120),
        Column(tr("Расход"), lambda r: r.money_out, money=True, width=120),
        Column(tr("Остаток"), lambda r: r.balance, money=True, width=130),
    ]
