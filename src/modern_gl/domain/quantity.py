"""Quantities: whole millionths of a unit (a chair, a kilogram), never `float`. The stock
module and the quantity of a posting (D-new) count in the same units."""

from __future__ import annotations

from decimal import Decimal

from modern_gl.domain.money import read_decimal
from modern_gl.i18n import tr

QUANTITY_SCALE = 6
QUANTITY_FACTOR = 10**QUANTITY_SCALE
_QUANTITY_QUANTUM = Decimal(1).scaleb(-QUANTITY_SCALE)


def to_quantity(value: str | int | Decimal) -> int:
    """Convert a user quantity to millionths of a base unit, without float rounding."""
    result = read_decimal(value, "quantities")
    if result != result.quantize(_QUANTITY_QUANTUM):
        raise ValueError(
            tr("больше {n} знаков после запятой: {value}", n=QUANTITY_SCALE, value=value)
        )
    return int(result.scaleb(QUANTITY_SCALE))


def format_quantity(quantity: int, precision: int = 3) -> str:
    """Format an internal quantity without insignificant zeroes."""
    value = Decimal(quantity).scaleb(-QUANTITY_SCALE)
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
