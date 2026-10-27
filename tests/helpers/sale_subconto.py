"""Shared from test_sale_subconto.py (moved here: other test modules use it too)."""

from __future__ import annotations

from tests.helpers.sales import Shop


def sales_groups(shop: Shop, *names: str) -> tuple[int, list[int]]:
    """A directory «Satış qrupları» on 46 and its elements."""
    kind = shop.ledger.add_subconto_kind(shop.company_id, None, "Satış qrupları")
    groups = [shop.ledger.add_subconto_value(shop.company_id, kind, name) for name in names]
    shop.ledger.update_account(shop.company_id, shop.acc["46"], subconto=[kind])
    return kind, groups


def postings_46(shop: Shop, conn, inv_doc: int) -> list[tuple]:
    """(Dt, Kt, amount, the sales group on the 46 side) of a document's postings."""
    gl = shop.inventory.load_document(shop.company_id, inv_doc).gl_document_id
    code = {v: k for k, v in shop.acc.items()}
    acc46 = shop.acc["46"]
    return [
        (
            code[p["debit_account_id"]],
            code[p["credit_account_id"]],
            p["amount"],
            p["dt_sc1"]
            if p["debit_account_id"] == acc46
            else p["ct_sc1"]
            if p["credit_account_id"] == acc46
            else None,
        )
        for p in conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl,)
        )
    ]
