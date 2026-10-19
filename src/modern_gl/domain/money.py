"""Money is an int of minor units (1 AZN = 100 qəpik). No floats anywhere."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from modern_gl.i18n import tr

SCALE = 2
_QUANTUM = Decimal(1).scaleb(-SCALE)


def to_minor(value: str | int | Decimal) -> int:
    """Convert '1 234,50' / Decimal('1234.5') / 1234 to minor units.

    More than two decimal places is an error, never silently rounded.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("amounts must be str, int or Decimal, never float")
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError(tr("не число: {value}", value=value)) from None
    if not d.is_finite():
        raise ValueError(tr("не число: {value}", value=value))
    if d != d.quantize(_QUANTUM):
        raise ValueError(tr("больше {n} знаков после запятой: {value}", n=SCALE, value=value))
    return int(d.scaleb(SCALE))


def format_minor(minor: int) -> str:
    """12345678 -> '123 456.78'"""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**SCALE)
    return f"{sign}{whole:,}.{frac:0{SCALE}d}".replace(",", " ")
