"""Money is an int of minor units (1 AZN = 100 qəpik). No floats anywhere."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

from modern_gl.i18n import tr

SCALE = 2
_QUANTUM = Decimal(1).scaleb(-SCALE)


def read_decimal(value: str | int | Decimal, what: str = "amounts") -> Decimal:
    """'1 234,50' (spaces, a non-breaking one too; a comma) / Decimal / int -> a finite
    Decimal: how amounts, quantities and rates are typed and pasted. Never a float."""
    if isinstance(value, (bool, float)):
        raise TypeError(f"{what} must be str, int or Decimal, never float")
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError(tr("не число: {value}", value=value)) from None
    if not d.is_finite():
        raise ValueError(tr("не число: {value}", value=value))
    return d


def to_minor(value: str | int | Decimal) -> int:
    """Convert '1 234,50' / Decimal('1234.5') / 1234 to minor units.

    More than two decimal places is an error, never silently rounded.
    """
    d = read_decimal(value)
    if d != d.quantize(_QUANTUM):
        raise ValueError(tr("больше {n} знаков после запятой: {value}", n=SCALE, value=value))
    return int(d.scaleb(SCALE))


def portal_minor(value: object) -> int:
    """An amount the e-taxes portal sends (a JSON number, «12.4369», None or "") in minor
    units, halves away from zero: 0.125 -> 0.13. Not a number — an error. A JSON float is
    read by its text (str(12.43) is «12.43»), never computed with."""
    if value is None or value == "":
        return 0
    number = read_decimal(str(value))
    return to_minor(number.quantize(_QUANTUM, rounding=ROUND_HALF_UP))


def round_half_away(value: Fraction) -> int:
    """Round an exact value to an integer, halves away from zero (0.5 -> 1, -0.5 -> -1)."""
    whole = int(abs(value))
    if abs(value) - whole >= Fraction(1, 2):
        whole += 1
    return whole if value >= 0 else -whole


def round_ratio(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded to an integer, halves away from zero — as
    `round_half_away` of the exact `Fraction`, in integers (the ƏDV reports round so for
    every e-qaimə)."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    whole, rest = divmod(abs(numerator), denominator)
    if 2 * rest >= denominator:
        whole += 1
    return whole if numerator >= 0 else -whole


def from_minor(minor: int) -> Decimal:
    """Stored minor units back to the exact value: 12345 -> Decimal('123.45')."""
    return Decimal(minor).scaleb(-SCALE)


def format_minor(minor: int) -> str:
    """12345678 -> '123 456.78'"""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**SCALE)
    return f"{sign}{whole:,}.{frac:0{SCALE}d}".replace(",", " ")
