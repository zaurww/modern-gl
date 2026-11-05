"""Which accounts keep a quantity (D199): an asset account, not a contra one, whose
subconto is a directory of objects — fixed assets, intangibles, any directory where each
purchase line is its own element (D194: low-value items on 12). 01, 08, 12 count; 02,
26, 60 do not. Goods (10, 41) are counted by the stock module, which posts no quantity:
they are not. Nothing is stored: the rule follows the chart."""

from __future__ import annotations

from modern_gl.infrastructure.db import Connection

# the condition on `accounts a` (a SQL fragment the reports and the checks share)
COUNTED = """(
    a.is_group = 0 AND a.contra = 0 AND a.account_class = 'asset'
    AND EXISTS (
        SELECT 1 FROM subconto_kinds k
        WHERE k.company_id = a.company_id
          AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
          AND k.per_line = 1
    )
)"""


def counted_accounts(conn: Connection, company_id: int) -> set[int]:
    """The accounts of the company that keep a quantity."""
    return {
        r["id"]
        for r in conn.execute(
            f"SELECT a.id FROM accounts a WHERE a.company_id = ? AND {COUNTED}", (company_id,)
        )
    }


def is_counted(conn: Connection, company_id: int, account_id: int | None) -> bool:
    """Whether this account keeps a quantity."""
    return account_id is not None and (
        conn.execute(
            f"SELECT 1 FROM accounts a WHERE a.company_id = ? AND a.id = ? AND {COUNTED}",
            (company_id, account_id),
        ).fetchone()
        is not None
    )
