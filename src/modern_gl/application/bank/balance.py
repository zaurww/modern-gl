"""The balance of an account, of one element of its subconto or all of them, at the end of
a day — one query for the bank account of a statement and the counterparty of a payment."""

from __future__ import annotations

from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection


def account_balance(
    conn: Connection,
    company_id: int,
    account_id: int,
    value_id: int | None,
    day: str,
    *,
    in_currency: bool = False,
) -> int:
    """Dt − Kt of the account at the end of the day (posted, the common book): of the
    subconto element `value_id` on any position, or of the whole account (None). In
    manat, or in the currency of the postings (`in_currency`)."""
    amount = "COALESCE(p.currency_amount, 0)" if in_currency else "p.amount"
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE
            WHEN p.debit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.dt_sc1, p.dt_sc2, p.dt_sc3)) THEN {amount}
            ELSE 0 END), 0)
             - COALESCE(SUM(CASE
            WHEN p.credit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.ct_sc1, p.ct_sc2, p.ct_sc3)) THEN {amount}
            ELSE 0 END), 0)
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        WHERE p.company_id = :c AND d.doc_date <= :day
          AND (p.debit_account_id = :a OR p.credit_account_id = :a)
        """,
        {"c": company_id, "a": account_id, "v": value_id, "day": iso_date(day)},
    ).fetchone()
    return row[0]
