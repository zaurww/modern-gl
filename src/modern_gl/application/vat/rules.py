"""The rule of the ƏDV credit, in versions by the date it is in force from. Versions are
never removed: a period is computed by the rule of its own time, whatever the program's
version; a period before the first known version is an error, not the nearest rule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr


@dataclass(frozen=True)
class CreditRule:
    """What counts for the credit of input ƏDV on a purchase.

    An e-qaimə is credited when it exists and both its amount and its ƏDV are paid — the
    amount from a bank account, the ƏDV to the supplier's deposit account — on the day of
    the later payment. `partial_share`: paid in part, the credit grows with the share paid
    (the ƏDV paid, but no more than the share of the amount paid); otherwise nothing until
    paid in full. A customs declaration is credited as its ƏDV is paid to the customs, the
    goods paid or not."""

    valid_from: str
    partial_share: bool = True


# each version from the day it applies; the first known is 2024 (the user's practice)
RULES = (CreditRule("2024-01-01"),)


def rule_for(day: date | str) -> CreditRule:
    """The version in force on `day`."""
    iso = iso_date(day)
    known = [rule for rule in RULES if rule.valid_from <= iso]
    if not known:
        raise ValidationError(tr("правил ƏDV за {year} год в программе нет", year=iso[:4]))
    return known[-1]
