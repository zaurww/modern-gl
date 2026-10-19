"""Account classes and the normal side of a balance."""

from __future__ import annotations

ACCOUNT_CLASSES = ("asset", "liability", "equity", "revenue", "expense")
DEBIT_NORMAL = {"asset", "expense"}  # liability, equity, revenue: credit-normal


def normal_side(account_class: str | None, contra: bool = False) -> str | None:
    """'debit' or 'credit'; a contra account sits on the opposite side. None if unknown."""
    if account_class is None:
        return None
    debit = account_class in DEBIT_NORMAL
    return "debit" if debit != contra else "credit"


def wrong_side(account_class: str | None, contra: bool, two_sided: bool, net: int) -> bool:
    """True if a net balance (Dt - Ct) sits on the side the account should not have.

    Two-sided accounts (settlements with counterparties, taxes…) are never flagged.
    """
    if two_sided or net == 0:
        return False
    side = normal_side(account_class, contra)
    if side is None:
        return False
    return (net > 0) != (side == "debit")
