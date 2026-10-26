"""Kapital Bank's statement («Hesabdan çıxarış / Account statement», Excel of the internet
bank): pairs of label and value over the table (account, currency, VÖEN, period,
balances — «3816.99 EUR (7280.53 AZN)»), then a row of headers and a line per movement.

What the form holds that is not plain:
- «Məbləğ» is in the account's currency, signed; «Valyuta» beside it may name another
  currency (a conversion names the other account's) — the currency is the header's;
- «Sənədin nömrəsi» is «34904613575 / 1370756096»: the line's own number, then the
  operation's — a payment and its fee share the second;
- «Əks hesabın nömrəsi, adı və vöen-i» is «IBAN / name / VÖEN»; abroad the third part is
  no VÖEN and the name may hold « / » itself."""

from __future__ import annotations

import re
from collections.abc import Sequence

from modern_gl.application.bank.files import BankFile, BankFileError, BankFormat, FileLine
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr

BANK = "Kapital Bank"
BANK_TIN = "9900003611"
TITLE = "Hesabdan çıxarış"
BANK_CODE = "AIIB"  # in the account's IBAN: AZ85AIIB4004…
HEADERS = {
    "№": "n",
    "Tarix": "day",
    "Sənədin nömrəsi": "number",
    "Əks hesabın nömrəsi, adı və vöen-i": "other",
    "Məbləğ": "amount",
    "AZN dəyəri": "base",
    "Balans": "balance",
    "Təyinat": "memo",
}
LABELS = {  # the beginning of a label over the table -> what its value is
    "Hesab nömrəsi": "iban",
    "Hesabın valyutası": "currency",
    "VÖEN": "tin",
    "Dövr üçün": "period",
    "İlkin qalıq": "opening",
    "Son qalıq": "closing",
}
DATE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")
TIN = re.compile(r"\d{10}")


def recognises(rows: Sequence[Sequence[str]]) -> bool:
    head = [c for row in rows[:12] for c in row if c]
    return any(c.startswith(TITLE) for c in head) and any(
        c.replace(" ", "")[4:8] == BANK_CODE for c in head if c.startswith("AZ")
    )


def read(rows: Sequence[Sequence[str]], file_name: str) -> BankFile:
    values = _labels(rows)
    missing = [label for label, key in LABELS.items() if key not in values]
    if missing:
        raise BankFileError(tr("{file}: в шапке нет «{label}»", file=file_name, label=missing[0]))
    days = DATE.findall(values["period"])
    if len(days) != 2:
        raise BankFileError(
            tr("{file}: не понят период «{text}»", file=file_name, text=values["period"])
        )
    start, columns = _table(rows, file_name)
    lines = []
    for n, row in enumerate(rows[start:], start + 1):
        cells = {key: (row[i] if i < len(row) else "") for key, i in columns.items()}
        if not any(cells.values()):
            break
        lines.append(_line(cells, file_name, n))
    return BankFile(
        bank=BANK,
        bank_tin=BANK_TIN,
        file_name=file_name,
        iban="".join(values["iban"].split()).upper(),
        currency=values["currency"].strip().upper(),
        owner_tin=values["tin"].strip(),
        date_from=_iso(days[0]),
        date_to=_iso(days[1]),
        opening=_first_amount(values["opening"], file_name),
        closing=_first_amount(values["closing"], file_name),
        lines=tuple(lines),
    )


def _labels(rows: Sequence[Sequence[str]]) -> dict[str, str]:
    """The header's values: a label is followed by its value in the next cell."""
    found: dict[str, str] = {}
    for row in rows[:12]:
        for i, cell in enumerate(row[:-1]):
            for label, key in LABELS.items():
                if cell.startswith(label) and key not in found:
                    found[key] = row[i + 1]
    return found


def _table(rows: Sequence[Sequence[str]], file_name: str) -> tuple[int, dict[str, int]]:
    """The first line's row and the column of each header."""
    for n, row in enumerate(rows):
        columns = {HEADERS[c.strip()]: i for i, c in enumerate(row) if c.strip() in HEADERS}
        if len(columns) == len(HEADERS):
            return n + 1, columns
    raise BankFileError(tr("{file}: не найдена строка заголовков таблицы", file=file_name))


def _line(cells: dict[str, str], file_name: str, n: int) -> FileLine:
    day = DATE.search(cells["day"])
    if day is None:
        raise BankFileError(
            tr(
                "{file}, строка {n}: не понята дата «{text}»",
                file=file_name,
                n=n,
                text=cells["day"],
            )
        )
    own, _, operation = cells["number"].partition("/")
    iban, name, tin = other_side(cells["other"])
    try:
        amount, balance = to_minor(cells["amount"]), to_minor(cells["balance"])
        base = to_minor(cells["base"] or "0")
    except ValueError as e:
        raise BankFileError(tr("{file}, строка {n}: {error}", file=file_name, n=n, error=e)) from e
    return FileLine(
        reference=own.strip(),
        group=operation.strip(),
        day=_iso(day.groups()),
        amount=amount,
        iban=iban,
        name=name,
        tin=tin,
        memo=" ".join(cells["memo"].split()),
        balance=balance,
        base_amount=base,
    )


def other_side(text: str) -> tuple[str, str, str]:
    """«AZ71AZRT… / RST GLOBAL MMC / 1005735471» -> (IBAN, name, VÖEN); abroad the last
    part is no VÖEN («LLC 'VIAL-CAS-BEL' / NOVODVORSKIJ S») or empty («SHENZHEN … /»):
    it stays in the name."""
    text = text.strip()
    if text.endswith("/"):  # no VÖEN: the cell's text ends with the separator
        text = text[:-1].rstrip() + " / "
    iban, _, rest = text.partition(" / ")
    name, _, last = rest.rpartition(" / ")
    if not name:  # «IBAN / name» only
        name, last = rest, ""
    last = last.strip()
    if last and not TIN.fullmatch(last):
        name, last = f"{name} / {last}", ""
    return "".join(iban.split()).upper(), " ".join(name.split()), last


def _first_amount(text: str, file_name: str) -> int:
    """«3816.99 EUR (7280.53 AZN)» -> 381699: the amount in the account's currency."""
    parts = text.split()
    try:
        return to_minor(parts[0]) if parts else 0
    except ValueError as e:
        raise BankFileError(tr("{file}: {error}", file=file_name, error=e)) from e


def _iso(day: Sequence[str]) -> str:
    d, m, y = day
    return f"{y}-{int(m):02d}-{int(d):02d}"


FORMAT = BankFormat(BANK, recognises, read)
