"""A statement file in Yapı Kredi Bank's form, as the internet bank gives it — for the
tests of bank statement files."""

from __future__ import annotations

from decimal import Decimal

from openpyxl import Workbook

from tests.helpers.excel import active_sheet

YK_IBAN = "AZ72KABA00000000000007871759"
HEADERS = [
    "Əməliyyat Tarixi",
    "Həyata Keçmə Tarixi",
    "Göndərən/Alıcı adı",
    "Göndərən/Alıcı Hesabı",
    "Əməliyyat Detalları",
    "Kredit",
    "Debit",
    "Balans",
]


def bank_number(value: Decimal) -> str:
    """Decimal("-36440.68") -> «-36.440,68»: as the bank writes amounts."""
    whole, _, cents = f"{abs(value):,.2f}".partition(".")
    return ("-" if value < 0 else "") + whole.replace(",", ".") + "," + cents


def bank_day(day: str) -> str:
    y, m, d = day.split("-")
    return f"{d}.{m}.{y}"


def yapikredi_file(path, opening, lines, iban=YK_IBAN, period=("2025-01-01", "2026-01-31")):
    """A statement in Yapı Kredi's form: `lines` — (day, name, IBAN, purpose, amount),
    money out below zero; the balances are counted as the bank shows them."""
    book = Workbook()
    sheet = active_sheet(book)
    closing = Decimal(opening) + sum(Decimal(x[4]) for x in lines)
    money_in = sum(Decimal(x[4]) for x in lines if Decimal(x[4]) > 0)
    rows: list[list[str]] = [
        [],
        [],
        ["Hesab Hərəkətləri"],
        [],
        ["Qurum Adı", "NUMUNE MMC"],
        ["Hesab No + Valyuta", f"{iban[-8:]} - AZN"],
        [],
        ["IBAN", iban],
        ["Başlanğıc Tarixi", bank_day(period[0])],
        ["Bitmə tarixi", bank_day(period[1])],
        ["Toplam Mədaxil", bank_number(Decimal(money_in)) + " AZN"],
        ["Toplam Məxaric", bank_number(closing - Decimal(opening) - money_in) + " AZN"],
        ["Əvvəlki Balans", bank_number(Decimal(opening))],
        ["Son Balans", bank_number(closing)],
        HEADERS,
        ["", "", "", "", "Əvvəlki Balans", "", "", bank_number(Decimal(opening))],
    ]
    balance = Decimal(opening)
    for day, name, other, memo, amount in lines:
        value = Decimal(amount)
        balance += value
        credit = bank_number(value) if value > 0 else ""
        debit = bank_number(value) if value < 0 else ""
        rows.append(
            [bank_day(day), bank_day(day), name, other, memo, credit, debit, bank_number(balance)]
        )
    rows.append(["", "", "", "", "Son Balans", "", "", bank_number(closing)])
    rows.append(["Tәrәflәr arasındakı mübahisәlәrdә Bank sistemi üzrə məlumatlar əsasdır."])
    for row in rows:
        sheet.append(row or [None])
    book.save(path)
    return path
