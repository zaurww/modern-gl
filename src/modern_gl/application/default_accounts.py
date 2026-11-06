"""Which account a new line or a new bank account starts with (debt 11): found by its role
or its type (D34, D35), not by a code — codes differ between charts (46 is sales in the
classic chart and stock in 1C 7.7; 80 is profit and loss in one, share capital in the
other)."""

from __future__ import annotations

from modern_gl.application.ledger import Ledger
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT, COST_OF_SALES, FX_GAIN, FX_LOSS
from modern_gl.domain.currency import NO_CURRENCY

SUPPLIER = "supplier"  # a purchase, the opening stock: what the company owes for goods
CUSTOMER = "customer"  # a sale
COST_OF_GOODS = "cost_of_goods"  # goods written off
RETAINED_EARNINGS = "retained_earnings"  # opening stock of a warehouse-only company (D90)
CURRENT_ACCOUNT = "current_account"  # a new bank account in manat
CURRENCY_ACCOUNT = "currency_account"  # in a currency
VAT_DEPOSIT_ACCOUNT = "vat_deposit_account"  # the ƏDV deposit (D41)
CARD_ACCOUNT = "card_account"  # a business card (D78)
EXCHANGE_GAIN = "exchange_gain"  # revaluation of currency balances
EXCHANGE_LOSS = "exchange_loss"
LANDED_COST = "landed_cost"  # where a batch's expense starts (D212)

# purpose -> (role, account type, currency: None any / False manat only / True currency)
_BY_ROLE = {
    COST_OF_GOODS: COST_OF_SALES,
    EXCHANGE_GAIN: FX_GAIN,
    EXCHANGE_LOSS: FX_LOSS,
    LANDED_COST: BATCH_EXPENSES_ACCOUNT,
}
_BY_TYPE: dict[str, tuple[str, bool | None]] = {
    SUPPLIER: ("payable", None),
    CUSTOMER: ("receivable", None),
    RETAINED_EARNINGS: ("retained_earnings", None),
    CURRENT_ACCOUNT: ("bank", False),
    CURRENCY_ACCOUNT: ("bank", True),
    VAT_DEPOSIT_ACCOUNT: ("vat_deposit", None),
}
# A card is a bank account with no type of its own; 1C 7.7 keeps cards on 55 «Специальные
# счета», the classic chart has none — then the current account (D78).
CARD_CODES = ("55",)
# The last resort, for a chart whose accounts have no types (typed by hand, or loaded from
# a file without them): the codes the program used before (debt 11).
UNTYPED_CODES = {
    SUPPLIER: ("60",),
    CUSTOMER: ("62",),
    COST_OF_GOODS: ("46",),
    RETAINED_EARNINGS: ("88", "84"),
    CURRENT_ACCOUNT: ("51",),
    CURRENCY_ACCOUNT: ("52",),
    VAT_DEPOSIT_ACCOUNT: ("54",),
    EXCHANGE_GAIN: ("80",),
    EXCHANGE_LOSS: ("80",),
}


def default_account(ledger: Ledger, company_id: int, purpose: str) -> int | None:
    """The account a `purpose` starts with; None — the company has none, the user picks."""
    if purpose == CARD_ACCOUNT:
        card = _leaf_by_code(ledger, company_id, CARD_CODES)
        return card or default_account(ledger, company_id, CURRENT_ACCOUNT)
    if purpose in _BY_ROLE:
        found = ledger.account_role(company_id, _BY_ROLE[purpose])
    else:
        found = _first_of_type(ledger, company_id, *_BY_TYPE[purpose])
    return found or _leaf_by_code(ledger, company_id, UNTYPED_CODES.get(purpose, ()))


def _first_of_type(
    ledger: Ledger, company_id: int, account_type: str, currency: bool | None
) -> int | None:
    """The first active posting account of the type in the chart's order (60.1, 62.1)."""
    rows = ledger.conn.execute(
        "SELECT id, currency FROM accounts WHERE company_id = ? AND account_type = ? "
        "AND is_group = 0 AND active = 1 ORDER BY code IS NULL, code",
        (company_id, account_type),
    ).fetchall()
    for row in rows:
        if currency is None or (row["currency"] != NO_CURRENCY) == currency:
            return row["id"]
    return None


def _leaf_by_code(ledger: Ledger, company_id: int, codes: tuple[str, ...]) -> int | None:
    for code in codes:
        row = ledger.conn.execute(  # the account itself, or the first under it (60 → 60.1)
            "SELECT id FROM accounts WHERE company_id = ? AND (code = ? OR code LIKE ?) "
            "AND is_group = 0 AND active = 1 ORDER BY code LIMIT 1",
            (company_id, code, f"{code}.%"),
        ).fetchone()
        if row is not None:
            return row["id"]
    return None
