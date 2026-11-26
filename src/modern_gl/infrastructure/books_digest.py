"""The figures of the books an update of the schema must leave as they were
(D224): every account's debit and credit turnover of each month and every
item's quantity and cost in each warehouse. Read before the pending migrations and after
them, inside the update's transaction: a difference stops the update and the file stays
the older program's file. Plain SQL over columns the tables have had since they appeared,
so the same reading works on the old schema and the new."""

from __future__ import annotations

import sqlite3

from modern_gl.i18n import tr

# a migration that means to change the figures says so in a line of its own, with the
# reason: `-- books-change: <why>`; the update it is part of is then not compared
INTENDED = "-- books-change:"

Digest = dict[tuple[str, int, int, str], tuple[int, int]]

_TURNOVER = """
    SELECT company_id, account, month, SUM(dt), SUM(ct) FROM (
        SELECT p.company_id, p.debit_account_id AS account,
               substr(d.doc_date, 1, 7) AS month, p.amount AS dt, 0 AS ct
        FROM postings p JOIN documents d ON d.id = p.document_id
        WHERE d.status = 'posted'
        UNION ALL
        SELECT p.company_id, p.credit_account_id, substr(d.doc_date, 1, 7), 0, p.amount
        FROM postings p JOIN documents d ON d.id = p.document_id
        WHERE d.status = 'posted'
    ) GROUP BY company_id, account, month
"""
_STOCK = """
    SELECT company_id, item_id, warehouse_id, SUM(quantity), SUM(amount)
    FROM stock_movements GROUP BY company_id, item_id, warehouse_id
"""
_STOCK_COLUMNS = {"company_id", "item_id", "warehouse_id", "quantity", "amount"}


def books(conn: sqlite3.Connection) -> Digest:
    """(kind, company, account or item, month or warehouse) → the two sums."""
    found: Digest = {}
    if _columns(conn, "postings") and _columns(conn, "documents"):
        for company, account, month, dt, ct in conn.execute(_TURNOVER):
            found["account", company, account, month] = (dt, ct)
    if _columns(conn, "stock_movements") >= _STOCK_COLUMNS:
        for company, item, warehouse, quantity, amount in conn.execute(_STOCK):
            found["stock", company, item, str(warehouse)] = (quantity, amount)
    return found


def difference(conn: sqlite3.Connection, before: Digest, after: Digest) -> str:
    """What the update would change in the books, for the user; "" — nothing."""
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if not changed:
        return ""
    kind, _company, subject, period = changed[0]
    if kind == "account":
        first = tr("обороты счёта {account} за {month}", account=_code(conn, subject), month=period)
    else:
        first = tr("остаток товара на складе (товар № {item})", item=subject)
    return tr(
        "обновление изменило бы цифры учёта: {first}; всего расхождений — {n}. "
        "Сообщите разработчику",
        first=first,
        n=len(changed),
    )


def intended(script: str) -> bool:
    """The migration says it means to change the figures of the books."""
    return any(line.strip().startswith(INTENDED) for line in script.splitlines())


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _code(conn: sqlite3.Connection, account_id: int) -> str:
    """The account's code as the updated file has it; its number when there is none."""
    try:
        row = conn.execute("SELECT code FROM accounts WHERE id = ?", (account_id,)).fetchone()
    except sqlite3.DatabaseError:
        row = None
    return str(row[0]) if row and row[0] else f"№ {account_id}"
