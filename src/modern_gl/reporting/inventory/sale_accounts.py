"""The table of sale accounts in the warehouse settings (D-new-stock-sale-accounts): the
stock accounts and the revenue and cost of sales each has of its own."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.inventory.choices import Choice, stock_account_choices


@dataclass(frozen=True)
class SaleAccountsRow:
    """A stock account in the settings' table of sale accounts and the accounts chosen
    for the sales of its goods (role -> account); a role it lacks takes the company's."""

    stock_account: Choice
    own: dict[str, int]


def sale_account_rows(conn: Connection, company_id: int) -> list[SaleAccountsRow]:
    """The stock accounts the table shows: those goods are on and those with sale accounts
    of their own — every stock account while the company has neither."""
    own: dict[int, dict[str, int]] = {}
    for row in conn.execute(
        "SELECT stock_account_id, role, account_id FROM inventory_sale_accounts "
        "WHERE company_id = ?",
        (company_id,),
    ):
        own.setdefault(row["stock_account_id"], {})[row["role"]] = row["account_id"]
    shown = set(own) | {
        row["inventory_account_id"]
        for row in conn.execute(
            "SELECT DISTINCT inventory_account_id FROM inventory_items WHERE company_id = ?",
            (company_id,),
        )
    }
    return [
        SaleAccountsRow(account, own.get(account.id, {}))
        for account in stock_account_choices(conn, company_id)
        if not shown or account.id in shown
    ]
