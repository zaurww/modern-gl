"""«Сменить счёт у отмеченных» in the journal (D225): the marked
documents' lines on one account go to another, each document corrected where it was made
— the journal's own in the ledger, a purchase in the warehouse, a bank operation in the
bank — in one transaction: all of them or none."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.application.common import batches
from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger
from modern_gl.infrastructure.db import Connection, transaction


@dataclass(frozen=True)
class AccountChange:
    changed: int  # documents whose lines went to the new account
    left: int  # marked documents left as they were: no such line a person may change


def accounts_used(conn: Connection, company_id: int, doc_ids: Sequence[int]) -> list[int]:
    """The accounts of these documents' postings, the most used first."""
    used: dict[int, int] = {}
    for part in batches(list(doc_ids)):
        marks = ", ".join("?" for _ in part)
        for side in ("debit_account_id", "credit_account_id"):
            for account_id, n in conn.execute(
                f"SELECT {side}, COUNT(*) FROM postings WHERE company_id = ? "
                f"AND document_id IN ({marks}) GROUP BY {side}",
                (company_id, *part),
            ):
                used[account_id] = used.get(account_id, 0) + n
    return sorted(used, key=lambda account_id: (-used[account_id], account_id))


def change_account(
    ledger: Ledger, company_id: int, doc_ids: Sequence[int], old_id: int, new_id: int
) -> AccountChange:
    """The lines of the GL documents `doc_ids` on `old_id` go to `new_id`. A document a
    module made is changed by the module (its lines a person chose: a purchase's expense
    lines, a bank operation's lines); what a module works out itself — the goods' account,
    the VAT — stays, and so does a document of a module without such lines."""
    own: list[int] = []
    owned: dict[str, list[int]] = {}
    for part in batches(list(doc_ids)):
        marks = ", ".join("?" for _ in part)
        owners = {
            row["document_id"]: (row["module"], row["owner_id"])
            for row in ledger.conn.execute(
                "SELECT document_id, module, owner_id FROM document_owners "
                f"WHERE company_id = ? AND role = 'made' AND document_id IN ({marks})",
                (company_id, *part),
            )
        }
        for doc_id in part:
            if doc_id in owners:
                module, owner_id = owners[doc_id]
                owned.setdefault(module, []).append(owner_id)
            else:
                own.append(doc_id)
    purchases = list(dict.fromkeys(owned.pop("inventory", [])))
    operations = list(dict.fromkeys(owned.pop("bank", [])))
    asked = len(own) + len(purchases) + len(operations) + sum(len(v) for v in owned.values())
    with transaction(ledger.conn):
        changed = ledger.change_posting_account(company_id, own, old_id, new_id)
        if purchases:
            inventory = Inventory(ledger.conn, ledger.actor, ledger=ledger)
            changed += inventory.change_line_account(company_id, purchases, old_id, new_id)
        if operations:
            changed += ledger.bank.change_line_account(company_id, operations, old_id, new_id)
    return AccountChange(changed, asked - changed)
