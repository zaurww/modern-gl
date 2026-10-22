"""What is in stock: balances, an item's card and details, the groups of items."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key


@dataclass(frozen=True)
class StockBalance:
    item_id: int
    item_code: str | None
    item_name: str
    warehouse_id: int
    warehouse_name: str
    unit_code: str
    precision: int
    quantity: int
    amount: int
    group: str = ""  # the item's group in the directory: «Avadanlıq / Kabellər»
    item_value_id: int = 0  # the item's directory element


@dataclass(frozen=True)
class ItemDetails:
    """An item as its dialog shows it; `used` — a document has it (unit and account stay)."""

    id: int
    value_id: int
    unit_id: int
    inventory_account_id: int
    used: bool


@dataclass(frozen=True)
class StockCardLine:
    doc_date: str
    document_id: int
    number: int
    doc_type: str
    memo: str
    movement_type: str
    quantity_in: int
    quantity_out: int
    amount_in: int
    amount_out: int
    quantity_balance: int
    amount_balance: int


def stock_balances(
    conn: sqlite3.Connection,
    company_id: int,
    as_of: date | str | None = None,
    *,
    item_id: int | None = None,
    warehouse_id: int | None = None,
    include_zero: bool = False,
) -> list[StockBalance]:
    """Balances by item and warehouse, calculated only from posted movements."""
    clauses = ["m.company_id = ?", "d.status = 'posted'"]
    params: list[object] = [company_id]
    if as_of is not None:
        clauses.append("m.doc_date <= ?")
        params.append(iso_date(as_of))
    if item_id is not None:
        clauses.append("m.item_id = ?")
        params.append(item_id)
    if warehouse_id is not None:
        clauses.append("m.warehouse_id = ?")
        params.append(warehouse_id)
    having = "" if include_zero else "HAVING SUM(m.quantity) <> 0 OR SUM(m.amount) <> 0"
    rows = conn.execute(
        f"""
        SELECT m.item_id, iv.code AS item_code, iv.name AS item_name,
               iv.id AS item_value_id, m.warehouse_id, wv.name AS warehouse_name,
               u.code AS unit_code, u.precision,
               SUM(m.quantity) AS quantity, SUM(m.amount) AS amount
        FROM stock_movements m
        JOIN inventory_documents d ON d.id = m.document_id
        JOIN inventory_items i ON i.id = m.item_id
        JOIN subconto_values iv ON iv.id = i.subconto_value_id
        JOIN inventory_units u ON u.id = i.unit_id
        JOIN warehouses w ON w.id = m.warehouse_id
        JOIN subconto_values wv ON wv.id = w.subconto_value_id
        WHERE {" AND ".join(clauses)}
        GROUP BY m.item_id, iv.code, iv.name, iv.id, m.warehouse_id, wv.name, u.code,
                 u.precision
        {having}
        ORDER BY iv.name, wv.name
        """,
        params,
    ).fetchall()
    paths = group_paths(conn, company_id)
    balances = [
        StockBalance(**dict(row), group=paths.get(row["item_value_id"], "")) for row in rows
    ]
    # by group, as the directory shows them: the groups first, then the items without one
    balances.sort(key=lambda b: (b.group == "", sort_key(b.group)))
    return balances


def group_paths(conn: sqlite3.Connection, company_id: int) -> dict[int, str]:
    """For each directory element in a group: its groups, outermost first (D60)."""
    rows = conn.execute(
        "SELECT id, name, parent_id, is_group FROM subconto_values WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    paths: dict[int, str] = {}
    for row in rows:
        names, parent, seen = [], row["parent_id"], set()
        while parent is not None and parent in by_id and parent not in seen:
            seen.add(parent)
            names.append(by_id[parent]["name"])
            parent = by_id[parent]["parent_id"]
        if names:
            paths[row["id"]] = " / ".join(reversed(names))
    return paths


def item_details(conn: sqlite3.Connection, company_id: int, value_id: int) -> ItemDetails | None:
    """The item a directory element is, if it is one."""
    row = conn.execute(
        """
        SELECT i.id, i.subconto_value_id, i.unit_id, i.inventory_account_id,
               EXISTS (SELECT 1 FROM inventory_lines l WHERE l.item_id = i.id)
               OR EXISTS (SELECT 1 FROM stock_movements m WHERE m.item_id = i.id) AS used
        FROM inventory_items i WHERE i.company_id = ? AND i.subconto_value_id = ?
        """,
        (company_id, value_id),
    ).fetchone()
    if row is None:
        return None
    return ItemDetails(
        row["id"],
        row["subconto_value_id"],
        row["unit_id"],
        row["inventory_account_id"],
        bool(row["used"]),
    )


def stock_card(
    conn: sqlite3.Connection,
    company_id: int,
    item_id: int,
    warehouse_id: int,
    date_from: date | str | None = None,
    date_to: date | str | None = None,
) -> list[StockCardLine]:
    """Chronological movements with a running quantity and value balance."""
    clauses = [
        "m.company_id = ?",
        "m.item_id = ?",
        "m.warehouse_id = ?",
        "d.status = 'posted'",
    ]
    params: list[object] = [company_id, item_id, warehouse_id]
    if date_to is not None:
        clauses.append("m.doc_date <= ?")
        params.append(iso_date(date_to))
    rows = conn.execute(
        f"""
        SELECT m.doc_date, d.id AS document_id, d.number, d.doc_type, d.memo,
               m.movement_type, m.quantity, m.amount, m.id
        FROM stock_movements m
        JOIN inventory_documents d ON d.id = m.document_id
        WHERE {" AND ".join(clauses)}
        ORDER BY m.doc_date, d.id, m.id
        """,
        params,
    ).fetchall()
    start = iso_date(date_from) if date_from is not None else None
    quantity_balance = amount_balance = 0
    result: list[StockCardLine] = []
    for row in rows:
        quantity_balance += row["quantity"]
        amount_balance += row["amount"]
        if start is not None and row["doc_date"] < start:
            continue
        result.append(
            StockCardLine(
                row["doc_date"],
                row["document_id"],
                row["number"],
                row["doc_type"],
                row["memo"],
                row["movement_type"],
                max(row["quantity"], 0),
                max(-row["quantity"], 0),
                max(row["amount"], 0),
                max(-row["amount"], 0),
                quantity_balance,
                amount_balance,
            )
        )
    return result
