"""Yapı Kredi Bank Azərbaycan's statement («Hesab Hərəkətləri», Excel of the internet
bank): a label and its value per row over the table (the account «07871759 - AZN», IBAN,
the period, the balances), a row of headers, «Əvvəlki Balans», a line per movement,
«Son Balans».

What the form holds that is not plain:
- amounts are «80.077,83»: a point between thousands, a comma before the kopecks; money
  in is «Kredit», money out — «Debit», with its minus;
- a line has no number: its reference is made of what never changes — the day, the
  amount and the balance after it (two lines of a day never share all three);
- no VÖEN anywhere — neither the owner's nor the other side's: only a name and an IBAN;
- the bank's fee is a line without the other side whose purpose says so («Com. FIN MMC»,
  «PAYMENT ORDER COMMISSION», «405848 HESAB ACILIS KOM»): the form marks it (`fee`);
- «Əməliyyat Tarixi» is the day the balance moves (the lines are in its order),
  «Həyata Keçmə Tarixi» may be later — the first is the line's day."""

from __future__ import annotations

import re
from collections.abc import Sequence

from modern_gl.application.bank.files import BankFile, BankFileError, BankFormat, FileLine
from modern_gl.domain.money import to_minor
from modern_gl.i18n import fold, tr

BANK = "Yapı Kredi Bank"
TITLE = "Hesab Hərəkətləri"
BANK_CODE = "KABA"  # in the account's IBAN: AZ72KABA0000…
HEADERS = {
    "Əməliyyat Tarixi": "day",
    "Göndərən/Alıcı adı": "name",
    "Göndərən/Alıcı Hesabı": "iban",
    "Əməliyyat Detalları": "memo",
    "Kredit": "credit",
    "Debit": "debit",
    "Balans": "balance",
}
OPENING, CLOSING = "Əvvəlki Balans", "Son Balans"  # over the table and as its rows
LABELS = {  # a label over the table -> what its value is
    "IBAN": "iban",
    "Hesab No + Valyuta": "account",
    "Başlanğıc Tarixi": "from",
    "Bitmə tarixi": "to",
    OPENING: "opening",
    CLOSING: "closing",
}
CURRENCY = re.compile(r"\s*[A-Za-z]{3}$")  # «80.077,83 AZN»
DATE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")
# a purpose of the bank's fee, folded: «com. fin mmc», «comm-ib-hop-d.g.k», «payment
# order commission», «hesab acilis kom», «komissiya»
FEE = re.compile(r"^comm?\b|commission|\bkom\b|komissi")


def recognises(rows: Sequence[Sequence[str]]) -> bool:
    head = [c.strip() for row in rows[:16] for c in row if c]
    return TITLE in head and any(
        c.replace(" ", "")[4:8] == BANK_CODE for c in head if c.startswith("AZ")
    )


def read(rows: Sequence[Sequence[str]], file_name: str) -> BankFile:
    start, columns = _table(rows, file_name)
    values = _labels(rows[: start - 1])
    missing = [label for label, key in LABELS.items() if key not in values]
    if missing:
        raise BankFileError(tr("{file}: в шапке нет «{label}»", file=file_name, label=missing[0]))
    lines = []
    for n, row in enumerate(rows[start:], start + 1):
        cells = {key: (row[i].strip() if i < len(row) else "") for key, i in columns.items()}
        if not cells["day"] and cells["memo"] == CLOSING:  # the table ends; a note follows
            break
        if not any(cells.values()) or (not cells["day"] and cells["memo"] == OPENING):
            continue
        lines.append(_line(cells, file_name, n))
    return BankFile(
        bank=BANK,
        bank_tin="",
        file_name=file_name,
        iban="".join(values["iban"].split()).upper(),
        currency=values["account"].rpartition("-")[2].strip().upper(),
        owner_tin="",
        date_from=_day(values["from"], file_name, 0),
        date_to=_day(values["to"], file_name, 0),
        opening=_amount(values["opening"], file_name, 0),
        closing=_amount(values["closing"], file_name, 0),
        lines=tuple(lines),
    )


def _table(rows: Sequence[Sequence[str]], file_name: str) -> tuple[int, dict[str, int]]:
    """The row after the headers and the column of each header."""
    for n, row in enumerate(rows):
        columns = {HEADERS[c.strip()]: i for i, c in enumerate(row) if c.strip() in HEADERS}
        if len(columns) == len(HEADERS):
            return n + 1, columns
    raise BankFileError(tr("{file}: не найдена строка заголовков таблицы", file=file_name))


def _labels(rows: Sequence[Sequence[str]]) -> dict[str, str]:
    """The header's values: a label in the first cell, its value in the next."""
    found: dict[str, str] = {}
    for row in rows:
        if len(row) > 1 and row[0].strip() in LABELS:
            found.setdefault(LABELS[row[0].strip()], row[1].strip())
    return found


def _line(cells: dict[str, str], file_name: str, n: int) -> FileLine:
    day = _day(cells["day"], file_name, n)
    credit = _amount(cells["credit"], file_name, n)
    debit = _amount(cells["debit"], file_name, n)
    if (credit != 0) == (debit != 0) or credit < 0:
        raise BankFileError(
            tr(
                "{file}, строка {n}: сумма должна быть в одной из колонок — «Kredit» или «Debit»",
                file=file_name,
                n=n,
            )
        )
    amount = credit - abs(debit)
    balance = _amount(cells["balance"], file_name, n)
    name, iban = " ".join(cells["name"].split()), "".join(cells["iban"].split()).upper()
    memo = " ".join(cells["memo"].split())
    reference = f"YK{day.replace('-', '')}/{amount}/{balance}"
    return FileLine(
        reference=reference,
        group=reference,  # the form does not say whose fee a fee is
        day=day,
        amount=amount,
        iban=iban,
        name=name,
        tin="",
        memo=memo,
        balance=balance,
        base_amount=0,
        fee=amount < 0 and not (name or iban) and FEE.search(fold(memo)) is not None,
    )


def _amount(text: str, file_name: str, n: int) -> int:
    """«80.077,83 AZN» -> 8007783, «-30,00» -> -3000, "" -> 0. A cell Excel holds as a
    number comes with a point before the kopecks and no comma — read as it is."""
    text = CURRENCY.sub("", text.strip())
    if "," in text:
        text = text.replace(".", "")
    try:
        return to_minor(text or "0")
    except ValueError as e:
        raise BankFileError(_where(file_name, n, str(e))) from e


def _day(text: str, file_name: str, n: int) -> str:
    found = DATE.search(text)
    if found is None:
        raise BankFileError(_where(file_name, n, tr("не понята дата «{text}»", text=text)))
    d, m, y = found.groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


def _where(file_name: str, n: int, error: str) -> str:
    if n:
        return tr("{file}, строка {n}: {error}", file=file_name, n=n, error=error)
    return tr("{file}: {error}", file=file_name, error=error)


FORMAT = BankFormat(BANK, recognises, read)
