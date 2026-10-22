"""Quantities, amounts and their allocation: pure functions, no queries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from modern_gl.application.inventory.model import QUANTITY_SCALE, VAT_RATE_SCALE
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import round_ratio, to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row

_QUANTITY_QUANTUM = Decimal(1).scaleb(-QUANTITY_SCALE)


def to_quantity(value: str | int | Decimal) -> int:
    """Convert a user quantity to millionths of a base unit, without float rounding."""
    if isinstance(value, (bool, float)):
        raise TypeError("quantities must be str, int or Decimal, never float")
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(tr("не число: {value}", value=value)) from None
    if not result.is_finite():
        raise ValueError(tr("не число: {value}", value=value))
    if result != result.quantize(_QUANTITY_QUANTUM):
        raise ValueError(
            tr("больше {n} знаков после запятой: {value}", n=QUANTITY_SCALE, value=value)
        )
    return int(result.scaleb(QUANTITY_SCALE))


def vat_of(amount: int, rate: int | None) -> int:
    """VAT on an amount without VAT, rounded to a minor unit (half away from zero)."""
    return 0 if not rate else round_ratio(amount * rate, VAT_RATE_SCALE)


def format_quantity(quantity: int, precision: int = 3) -> str:
    """Format an internal quantity without insignificant zeroes."""
    value = Decimal(quantity).scaleb(-QUANTITY_SCALE)
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def money(minor: int) -> Decimal:
    """Convert stored minor units back to the exact value expected by PostingInput."""
    return Decimal(minor).scaleb(-MONEY_SCALE)


def allocate_minor(total: int, weights: Sequence[tuple[int, int]]) -> dict[int, int]:
    """Allocate every minor unit deterministically by largest remainder."""
    if total <= 0:
        raise ValidationError(tr("сумма должна быть положительной"))
    if not weights or any(weight < 0 for _, weight in weights):
        raise ValidationError(tr("неверная база распределения"))
    denominator = sum(weight for _, weight in weights)
    if denominator <= 0:
        raise ValidationError(tr("база распределения равна нулю"))
    result: dict[int, int] = {}
    remainders: list[tuple[int, int]] = []
    assigned = 0
    for key, weight in weights:
        value, remainder = divmod(total * weight, denominator)
        result[key] = value
        assigned += value
        remainders.append((remainder, key))
    for _, key in sorted(remainders, key=lambda pair: (-pair[0], pair[1]))[: total - assigned]:
        result[key] += 1
    return result


def split_charges(
    charges: Sequence[tuple[int, int]], targets: Mapping[int, int]
) -> dict[tuple[int, int], int]:
    """(charge, target) -> share: every charge is spread over the targets so that each
    charge and each target total come out exact (charges and targets sum to the same).

    Each charge goes in proportion to what the targets can still take, so the last one
    takes exactly the rest."""
    capacity = dict(targets)
    result: dict[tuple[int, int], int] = {}
    for charge_id, amount in charges:
        if amount <= 0:
            continue
        weights = [(key, left) for key, left in capacity.items() if left > 0]
        for key, share in allocate_minor(amount, weights).items():
            if share:
                result[(charge_id, key)] = share
                capacity[key] -= share
    return result


def positive_amount(value: str | int | Decimal | None, line_no: int) -> int:
    if value is None or blank(value):
        if line_no:
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        raise ValidationError(tr("сумма должна быть положительной"))
    try:
        amount = to_minor(value)
    except (TypeError, ValueError) as exc:
        prefix = tr("строка {line}: ", line=line_no) if line_no else ""
        raise ValidationError(f"{prefix}{exc}") from exc
    if amount <= 0:
        raise ValidationError(tr("сумма должна быть положительной"))
    return amount


def nonnegative_amount(value: str | int | Decimal) -> int:
    try:
        amount = to_minor(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    if amount < 0:
        raise ValidationError(tr("сумма не может быть отрицательной"))
    return amount


def typed_rate(rate: str | int | Decimal | None) -> int:
    """A typed rate (manat per unit) -> millionths."""
    if rate is None or blank(rate):
        raise ValidationError(tr("не указан курс валюты"))
    try:
        return parse_rate(rate)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc


def service_quantity(value: str | int | Decimal | None, line_no: int) -> int:
    """A service's quantity is optional (0: not given); no unit limits its decimals."""
    if value is None or blank(value):
        return 0
    try:
        quantity = to_quantity(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(tr("строка {line}: {error}", line=line_no, error=exc)) from exc
    if quantity <= 0:
        raise ValidationError(
            tr("строка {line}: количество должно быть положительным", line=line_no)
        )
    return quantity


def item_quantity(item: Row, value: str | int | Decimal | None, line_no: int) -> int:
    if value is None or blank(value):
        raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
    try:
        quantity = to_quantity(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(tr("строка {line}: {error}", line=line_no, error=exc)) from exc
    if quantity <= 0:
        raise ValidationError(
            tr("строка {line}: количество должно быть положительным", line=line_no)
        )
    precision = item["unit_precision"]
    if quantity % (10 ** (QUANTITY_SCALE - precision)):
        raise ValidationError(
            tr("строка {line}: для единицы допустимо знаков: {n}", line=line_no, n=precision)
        )
    return quantity


def draft_quantity(item: Row, value: str | int | Decimal | None, line_no: int) -> int:
    return 0 if blank(value) else item_quantity(item, value, line_no)
