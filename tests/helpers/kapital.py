"""A statement file in Kapital Bank's form, as the internet bank gives it — for the tests
of bank statement files."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook

from tests.helpers.excel import active_sheet

OWN_TIN = "1400000001"
VIAL = "LLC 'VIAL-CAS-BEL' / NOVODVORSKIJ S"
AZN_IBAN = "AZ11AIIB40040000000000000001"
EUR_IBAN = "AZ22AIIB40140000000000000002"
OWN_NAME = "″ALFA-BETA TEST″ MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ"
HEADERS = [
    "№",
    "Tarix",
    "Sənədin nömrəsi",
    "Əks hesabın nömrəsi, adı və vöen-i",
    "Məbləğ",
    "Valyuta",
    "AZN dəyəri",
    "Balans",
    "Təyinat",
]


def kapital_file(path, iban, currency, opening, lines, tin=OWN_TIN):
    """A statement in Kapital Bank's form: `lines` — (day, number, other side, amount,
    base amount, purpose); the balances are counted as the bank shows them."""
    book = Workbook()
    sheet = active_sheet(book)
    sheet.title = "Hesabdan Çıxarış"
    sheet["A1"] = "Hesabdan çıxarış / Account statement"
    closing = Decimal(opening) + sum(Decimal(x[3]) for x in lines)
    header = [
        ("Müştərinin Adı / Client's name", OWN_NAME, "Çıxarışın tarixi / Statement date", "x"),
        ("Hesab nömrəsi / Account number", iban, "Hesabın valyutası / Account currency", currency),
        (
            "Hesabın tipi / Account type",
            "Cari hesab",
            "Dövr üçün / For period",
            "01/08/2026 - 05/08/2026",
        ),
        ("VÖEN / Tax id", tin, "Filial adı / Branch name", "Port Baku (290)"),
        ("Cəmi dövriyyələr kredit", "0 AZN", "Cəmi dövriyyələr debit", "0 AZN"),
        ("İlkin qalıq", f"{opening} {currency} (0 AZN)", "Son qalıq", f"{closing} {currency}"),
    ]
    for n, row in enumerate(header, 4):
        for column, value in zip("ABCD", row, strict=True):
            sheet[f"{column}{n}"] = value
    for column, value in zip("ABCDEFGHI", HEADERS, strict=True):
        sheet[f"{column}13"] = value
    balance = Decimal(opening)
    for n, (day, number, other, amount, base, memo) in enumerate(lines, 1):
        balance += Decimal(amount)
        values = [n, datetime.fromisoformat(day), number, other, Decimal(amount), currency]
        values += [Decimal(base), balance, memo]
        for column, value in zip("ABCDEFGHI", values, strict=True):
            sheet[f"{column}{13 + n}"] = value
    book.save(path)
    return path
