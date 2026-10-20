"""Currencies and exchange rates. No floats: a rate is an int of millionths of a manat.

A rate is quoted for `nominal` units of the currency, like the Central Bank does
(1 USD = 1.7000 AZN, 100 JPY = 1.1300 AZN). Currency amounts are kept in minor
units with two decimals, the same as manat amounts.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction

from modern_gl.domain.money import round_half_away
from modern_gl.i18n import language, tr

RATE_SCALE = 6
RATE_UNIT = 10**RATE_SCALE

# Currency accounting of an account (accounts.currency):
NO_CURRENCY = 0  # manat only
CURRENCY_ONLY = 1  # every posting in a currency (52 — a currency bank account)
CURRENCY_OPTIONAL = 2  # in manat or in a currency (60, 62: local and foreign partners)
CURRENCY_MODES = (NO_CURRENCY, CURRENCY_ONLY, CURRENCY_OPTIONAL)


def currency_mode(value: bool | int) -> int:
    """True / False of older callers mean CURRENCY_ONLY / NO_CURRENCY."""
    mode = int(value)
    if mode not in CURRENCY_MODES:
        raise ValueError(f"currency mode {value!r}")
    return mode


# Currencies a new company starts with; others are added from KNOWN when needed.
DEFAULT_CURRENCIES = ("USD", "EUR", "RUB", "TRY", "GBP")
KNOWN = {  # code: (Russian, Azerbaijani)
    "USD": ("Доллар США", "ABŞ dolları"),
    "EUR": ("Евро", "Avro"),
    "RUB": ("Российский рубль", "Rusiya rublu"),
    "TRY": ("Турецкая лира", "Türkiyə lirəsi"),
    "GBP": ("Фунт стерлингов", "Britaniya funt sterlinqi"),
    "GEL": ("Грузинский лари", "Gürcüstan larisi"),
    "CNY": ("Китайский юань", "Çin yuanı"),
    "KZT": ("Казахстанский тенге", "Qazaxıstan tengesi"),
    "UAH": ("Украинская гривна", "Ukrayna qrivnası"),
    "CHF": ("Швейцарский франк", "İsveçrə frankı"),
    "AED": ("Дирхам ОАЭ", "BƏƏ dirhəmi"),
    "JPY": ("Японская иена", "Yaponiya yeni"),
    "KRW": ("Южнокорейская вона", "Cənubi Koreya vonu"),
    "IRR": ("Иранский риал", "İran rialı"),
    "BYN": ("Белорусский рубль", "Belarus rublu"),
    "UZS": ("Узбекский сум", "Özbəkistan somu"),
    "KGS": ("Киргизский сом", "Qırğızıstan somu"),
    "TMT": ("Туркменский манат", "Türkmənistan manatı"),
    "SAR": ("Саудовский риал", "Səudiyyə Ərəbistanı rialı"),
    "CAD": ("Канадский доллар", "Kanada dolları"),
    "AUD": ("Австралийский доллар", "Avstraliya dolları"),
    "SEK": ("Шведская крона", "İsveç kronu"),
    "NOK": ("Норвежская крона", "Norveç kronu"),
    "PLN": ("Польский злотый", "Polşa zlotısı"),
    "CZK": ("Чешская крона", "Çexiya kronu"),
}


def currency_name(code: str, lang: str | None = None) -> str:
    """Name of a well-known currency in the interface language; the code otherwise."""
    names = KNOWN.get(code.upper())
    if names is None:
        return code.upper()
    return names[1] if (lang or language()) == "az" else names[0]


def check_code(code: str) -> str:
    code = code.strip().upper()
    if len(code) != 3 or not code.isalpha() or not code.isascii():
        raise ValueError(tr("код валюты — три латинские буквы (USD, EUR…): {code}", code=code))
    return code


def parse_rate(text: str | int | Decimal) -> int:
    """'1,7' / '1.7000' / Decimal('1.7') -> 1700000 (millionths). Must be positive."""
    if isinstance(text, (bool, float)):
        raise TypeError("rates must be str, int or Decimal, never float")
    if isinstance(text, str):
        text = text.strip().replace(" ", "").replace(",", ".")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValueError(tr("не число: {value}", value=text)) from None
    if not d.is_finite() or d <= 0:
        raise ValueError(tr("курс должен быть больше нуля: {value}", value=text))
    scaled = d.scaleb(RATE_SCALE)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            tr("в курсе больше {n} знаков после запятой: {value}", n=RATE_SCALE, value=text)
        )
    return int(scaled)


def format_rate(rate: int, nominal: int = 1) -> str:
    """1700000 -> '1.7000': the manat price of one unit (100 JPY at 1130000 -> '0.0113')."""
    return format_unit_rate(unit_rate(rate, nominal))


def format_unit_rate(value: Fraction) -> str:
    """Manat per unit, with at least 4 decimals and up to 6 when they matter."""
    scaled = round_half_away(value * RATE_UNIT)
    whole, frac = divmod(abs(scaled), RATE_UNIT)
    digits = f"{frac:0{RATE_SCALE}d}".rstrip("0").ljust(4, "0")
    return f"{'-' if scaled < 0 else ''}{whole}.{digits}"


def unit_rate(rate: int, nominal: int = 1) -> Fraction:
    """Manat per one unit of the currency, exact."""
    return Fraction(rate, RATE_UNIT * nominal)


def to_base(currency_minor: int, rate: Fraction) -> int:
    """A currency amount (minor units) at `rate` (manat per unit) -> qəpik,
    rounded half away from zero."""
    return round_half_away(currency_minor * rate)
