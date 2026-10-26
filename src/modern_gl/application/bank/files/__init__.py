"""Bank statements from files: every bank has a form of its own — a module per bank
(`kapital`), each recognises its form and reads it into the same `BankFile`. A new bank —
a new module and its line in `FORMATS`; nothing else changes.

A file is read whole and checked against itself: the balance after every line, the
opening and closing balances — a file read wrong never reaches the books."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.table_files import read_rows


class BankFileError(LedgerError):
    pass


@dataclass(frozen=True)
class FileLine:
    """One movement of money as the bank's file shows it, in minor units."""

    reference: str  # the bank's number of the line: one per line, the same in every file
    group: str  # the bank's operation: a payment and its fee share it
    day: str  # ISO date
    amount: int  # in the account's currency: money in > 0, out < 0
    iban: str  # the other side's account (abroad — any number)
    name: str  # the other side's name
    tin: str  # its VÖEN ("" abroad or unknown)
    memo: str  # the purpose of payment
    balance: int  # the account's balance after the line
    base_amount: int  # the bank's value in manat, signed as `amount`


@dataclass(frozen=True)
class BankFile:
    """A statement read from a file: whose account, what period, the lines in order."""

    bank: str  # the form's name: "Kapital Bank"
    bank_tin: str  # the bank's VÖEN: lines from it are its fees (and its services)
    file_name: str
    iban: str
    currency: str  # "AZN", "USD"…
    owner_tin: str  # the VÖEN of the account's owner
    date_from: str
    date_to: str
    opening: int
    closing: int
    lines: tuple[FileLine, ...]


@dataclass(frozen=True)
class BankFormat:
    """A bank's form: `recognises` the rows of a file, `read` makes a `BankFile` of them."""

    bank: str
    recognises: Callable[[Sequence[Sequence[str]]], bool]
    read: Callable[[Sequence[Sequence[str]], str], BankFile]


def _formats() -> tuple[BankFormat, ...]:
    from modern_gl.application.bank.files import kapital

    return (kapital.FORMAT,)


def read_bank_file(path: str | Path) -> BankFile:
    """The statement in the file, by the first form that recognises it; checked."""
    path = Path(path)
    rows = read_rows(path)
    formats = _formats()
    for form in formats:
        if form.recognises(rows):
            found = form.read(rows, path.name)
            check_balances(found)
            return found
    raise BankFileError(
        tr(
            "{file}: форма выписки не распознана. Понятны выписки: {banks}",
            file=path.name,
            banks=", ".join(f.bank for f in formats),
        )
    )


def check_balances(found: BankFile) -> None:
    """The opening balance and the lines give every balance the file shows: else the file
    was read wrong (or is not whole) — nothing of it is loaded."""
    balance = found.opening
    for n, line in enumerate(found.lines, 1):
        balance += line.amount
        if balance != line.balance:
            raise BankFileError(
                tr(
                    "{file}, строка {n}: остаток {shown} в файле, а по строкам {counted} — "
                    "файл прочитан неверно",
                    file=found.file_name,
                    n=n,
                    shown=format_minor(line.balance),
                    counted=format_minor(balance),
                )
            )
    if balance != found.closing:
        raise BankFileError(
            tr(
                "{file}: остаток на конец {shown} в файле, а по строкам {counted} — файл "
                "прочитан неверно",
                file=found.file_name,
                shown=format_minor(found.closing),
                counted=format_minor(balance),
            )
        )


__all__ = ["BankFile", "BankFileError", "BankFormat", "FileLine", "read_bank_file"]
