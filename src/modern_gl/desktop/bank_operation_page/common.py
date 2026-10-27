"""Helpers of the bank operation form: the bank field, the e-qaimə list, picking by data."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QLabel

from modern_gl.application.bank import (
    BANK_TYPES,
    CUSTOMER,
    OTHER,
    SUPPLIER,
    BankPlace,
)
from modern_gl.application.catalog import AccountInfo, SubcontoInfo
from modern_gl.application.invoices import DRAFT, PORTAL, OpenInvoice
from modern_gl.desktop.pick import PickBox, SuggestBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import ru_date
from modern_gl.domain.currency import CURRENCY_ONLY, NO_CURRENCY
from modern_gl.domain.money import format_minor
from modern_gl.i18n import N_, tr

NONE = "—"
# the line's account suggests the kind of a counterparty's operation
TYPE_KINDS = {
    "payable": SUPPLIER,
    "advance_paid": SUPPLIER,
    "receivable": CUSTOMER,
    "advance_received": CUSTOMER,
}
WITH_COUNTERPARTY = (SUPPLIER, CUSTOMER, OTHER)
SEVERAL = "several"  # the list item «several e-qaimə…»
FROM_BANK = "from_bank"  # the ƏDV part from this account to the supplier's deposit
# an e-qaimə the books do not have yet: an imported draft, or only seen on the portal
SOURCES = {DRAFT: N_("черновик"), PORTAL: N_("с портала")}


FIELD_WIDTH = 460  # the fields on the cursor's path


def caption(text: str, name: str = "secondary") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


def place_label(place: BankPlace) -> str:
    """A bank account in one field: «ABB · 51 · AZN»."""
    return f"{place.name}  ·  {place.account_code}  ·  {place.currency or 'AZN'}"


def offer_invoices(box: SuggestBox, invoices: Sequence[OpenInvoice]) -> None:
    """The e-qaimə a list offers: number, date, what is left to pay, and where it is known
    from if not from the posted documents; «several» after them."""
    typed = box.text()
    box.clear()
    for i in invoices:
        label = f"{i.invoice} · {ru_date(i.doc_date)} · {format_minor(i.amount)}"
        if i.vat:
            label += f" · ƏDV {format_minor(i.vat)}"
        if i.source in SOURCES:
            label += f" · {tr(SOURCES[i.source])}"
        box.addItem(label, i, i.invoice)
    if len(invoices) > 1:
        box.addItem(tr("Несколько e-qaimə…"), SEVERAL, "")
    box.setText(typed)


def bank_accounts(session: Session) -> list[AccountInfo]:
    """Accounts money is in the bank on: by type, or by the bank account directory."""
    catalog = session.catalog
    return [
        a
        for a in catalog.leaf_accounts
        if a.account_type in BANK_TYPES
        or (
            a.account_type is None
            and any(catalog.kind_codes.get(k or 0) == "bank_account" for k in a.sc_kinds)
        )
    ]


def counterparty_kind(session: Session) -> int | None:
    return next(
        (k for k, code in session.catalog.kind_codes.items() if code == "counterparty"), None
    )


def fits(account: AccountInfo | None, value: SubcontoInfo) -> bool:
    """A bank account fits a GL account by currency: a USD account is not offered on a
    manat-only 51, a manat one not on a currency-only 52."""
    if account is None:
        return True
    if value.currency_id is None:
        return account.currency != CURRENCY_ONLY
    return account.currency != NO_CURRENCY


def select_data(box: PickBox, data, text: str = "") -> None:
    """Choose the item with this data; one no longer offered (hidden) is added."""
    i = box.findData(data)
    if i < 0 and data is not None:
        box.addItem(text or str(data), data)
        i = box.count() - 1
    box.setCurrentIndex(i)
