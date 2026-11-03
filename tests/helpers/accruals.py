"""Shared by test_accrued_expenses.py and test_accrued_income.py (D65): the accrual
documents of a purchase or sale, turnovers and the count of documents."""

from __future__ import annotations

from tests.helpers.sales import Shop


def accrual(shop: Shop, document: int) -> list[tuple]:
    """(date, Dt code, Kt code, amount, memo) of the receipt's accrual documents, by month."""
    doc = shop.inventory.load_document(shop.company_id, document)
    code = {v: k for k, v in shop.acc.items()}
    return [
        (
            r["doc_date"],
            code[r["debit_account_id"]],
            code[r["credit_account_id"]],
            r["amount"],
            r["memo"],
        )
        for a in doc.accruals
        for r in shop.ledger.conn.execute(
            "SELECT d.doc_date, p.* FROM postings p JOIN documents d ON d.id = p.document_id "
            "WHERE d.id = ? ORDER BY p.line_no",
            (a.gl_document_id,),
        )
    ]


def accrual_ids(shop: Shop, document: int) -> list[int]:
    return [
        a.gl_document_id for a in shop.inventory.load_document(shop.company_id, document).accruals
    ]


def turnover(shop: Shop, code: str, date_from: str, date_to: str) -> tuple[int, int]:
    """(debit, credit) turnover of an account over posted documents in the dates."""
    row = shop.ledger.conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN p.debit_account_id = :a THEN p.amount END), 0), "
        "COALESCE(SUM(CASE WHEN p.credit_account_id = :a THEN p.amount END), 0) "
        "FROM postings p JOIN documents d ON d.id = p.document_id "
        "WHERE d.status = 'posted' AND d.doc_date BETWEEN :f AND :t",
        {"a": shop.acc[code], "f": date_from, "t": date_to},
    ).fetchone()
    return row[0], row[1]


def documents(shop: Shop) -> int:
    return shop.ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
