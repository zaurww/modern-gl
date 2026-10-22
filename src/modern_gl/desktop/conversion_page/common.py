"""What the conversion's parts share: the money accounts and their currency, amounts as text."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QComboBox

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import CURRENCY_OPTIONAL
from modern_gl.domain.money import format_minor

MONEY_TYPES = ("cash", "bank")
NONE = "—"
BASE = "AZN"  # the manat: amounts without a currency


def money_accounts(session: Session) -> list[AccountInfo]:
    """Where money is kept: cash and bank accounts (by type, or by the bank account
    directory); a chart without either offers every account."""
    catalog = session.catalog
    found = [
        a
        for a in catalog.leaf_accounts
        if a.account_type in MONEY_TYPES
        or any(catalog.kind_codes.get(k or 0) == "bank_account" for k in a.sc_kinds)
    ]
    return found or catalog.leaf_accounts


def amount_text(minor: int) -> str:
    return format_minor(minor) if minor else ""


def fit_currency(
    box: QComboBox | PickBox,
    session: Session,
    account: AccountInfo | None,
    subconto: Sequence[int | None],
    preferred: int | None = None,
) -> None:
    """The currency follows the account: a manat account is in manat, a USD bank
    account in USD; a currency account without one lets the user choose."""
    chosen = box.currentData() if preferred is None else preferred
    box.clear()
    if account is None or not account.currency:
        box.addItem(BASE, None)
        box.setCurrentIndex(0)
        box.setEnabled(False)
        return
    catalog = session.catalog
    fixed = next(
        (
            catalog.value(v).currency_id
            for v in subconto
            if v is not None and catalog.value(v).currency_id is not None
        ),
        None,
    )
    if fixed is not None:
        box.addItem(catalog.currencies[fixed].code, fixed)
        box.setCurrentIndex(0)
        box.setEnabled(False)
        return
    if account.currency == CURRENCY_OPTIONAL:
        box.addItem(BASE, None)
    for c in catalog.active_currencies:
        box.addItem(c.code, c.id)
    box.setEnabled(True)
    box.setCurrentIndex(max(box.findData(chosen), 0))


def money_places(session: Session) -> list[tuple[str, tuple[int, tuple[int | None, ...]]]]:
    """Where a fee can be taken from: every bank account (an element of the account's first
    directory: "Kapital Bank USD · 52") and every money account without one."""
    catalog = session.catalog
    places = []
    for account in money_accounts(session):
        kind = account.sc_kinds[0]
        if kind is None:
            places.append((account.label, (account.id, ())))
            continue
        places.extend(
            (f"{value.name}  ·  {account.short}", (account.id, (value.id,)))
            for value in catalog.values(kind)
        )
    return places
