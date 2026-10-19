"""Read models for the quantitative/value inventory register."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from modern_gl.domain.dates import iso_date


def code_label(code: str | None, name: str) -> str:
    """'code  name' for lists, or just the name when there is no code."""
    return f"{code}  {name}" if code else name


@dataclass(frozen=True)
class Choice:
    """An entry offered in a list: id and the text shown for it."""

    id: int
    label: str


@dataclass(frozen=True)
class ItemChoice(Choice):
    unit: str
    precision: int


@dataclass(frozen=True)
class ReceiptLineChoice:
    """A posted receipt line that landed cost can be allocated to."""

    id: int
    doc_date: str
    number: int
    item_name: str
    quantity: int
    amount: int
    precision: int


@dataclass(frozen=True)
class InventoryDocumentSummary:
    id: int
    number: int
    doc_date: str
    doc_type: str
    memo: str
    status: str
    gl_document_id: int | None
    cost_type_name: str | None
    amount: int


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
               m.warehouse_id, wv.name AS warehouse_name,
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
        GROUP BY m.item_id, iv.code, iv.name, m.warehouse_id, wv.name, u.code, u.precision
        {having}
        ORDER BY iv.name, wv.name
        """,
        params,
    ).fetchall()
    return [StockBalance(**dict(row)) for row in rows]


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


def item_choices(conn: sqlite3.Connection, company_id: int) -> list[ItemChoice]:
    """Active items with their unit, by name."""
    rows = conn.execute(
        """
        SELECT i.id, v.code, v.name, u.code AS unit_code, u.precision
        FROM inventory_items i
        JOIN subconto_values v ON v.company_id = i.company_id AND v.id = i.subconto_value_id
        JOIN inventory_units u ON u.company_id = i.company_id AND u.id = i.unit_id
        WHERE i.company_id = ? AND v.active = 1
        ORDER BY v.name
        """,
        (company_id,),
    )
    return [
        ItemChoice(r["id"], code_label(r["code"], r["name"]), r["unit_code"], r["precision"])
        for r in rows
    ]


def warehouse_choices(conn: sqlite3.Connection, company_id: int) -> list[Choice]:
    """Active warehouses, by name."""
    rows = conn.execute(
        """
        SELECT w.id, v.code, v.name FROM warehouses w
        JOIN subconto_values v ON v.company_id = w.company_id AND v.id = w.subconto_value_id
        WHERE w.company_id = ? AND v.active = 1 ORDER BY v.name
        """,
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def unit_choices(conn: sqlite3.Connection, company_id: int) -> list[Choice]:
    """Active units of measure, by name."""
    rows = conn.execute(
        "SELECT id, code, name FROM inventory_units WHERE company_id = ? AND active = 1 "
        "ORDER BY name",
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def landed_cost_type_choices(conn: sqlite3.Connection, company_id: int) -> list[Choice]:
    """Active kinds of additional costs, by name."""
    rows = conn.execute(
        "SELECT id, code, name FROM landed_cost_types "
        "WHERE company_id = ? AND active = 1 ORDER BY name",
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def stock_account_choices(conn: sqlite3.Connection, company_id: int) -> list[Choice]:
    """Active posting accounts that track both item and warehouse subconto."""
    rows = conn.execute(
        """
        SELECT a.id, a.code, a.name FROM accounts a
        WHERE a.company_id = ? AND a.active = 1 AND a.is_group = 0
          AND EXISTS (
            SELECT 1 FROM subconto_kinds k WHERE k.company_id = a.company_id
              AND k.code = 'item' AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
          )
          AND EXISTS (
            SELECT 1 FROM subconto_kinds k WHERE k.company_id = a.company_id
              AND k.code = 'warehouse'
              AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
          )
        ORDER BY a.code IS NULL, a.code, a.name
        """,
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def has_units(conn: sqlite3.Connection, company_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM inventory_units WHERE company_id = ? LIMIT 1", (company_id,)
        ).fetchone()
        is not None
    )


def receipt_line_choices(conn: sqlite3.Connection, company_id: int) -> list[ReceiptLineChoice]:
    """Posted opening and receipt lines, newest first."""
    rows = conn.execute(
        """
        SELECT l.id, d.doc_date, d.number, v.name AS item_name, l.quantity, l.amount,
               u.precision
        FROM inventory_lines l
        JOIN inventory_documents d ON d.company_id = l.company_id AND d.id = l.document_id
        JOIN inventory_items i ON i.company_id = l.company_id AND i.id = l.item_id
        JOIN subconto_values v ON v.company_id = i.company_id AND v.id = i.subconto_value_id
        JOIN inventory_units u ON u.company_id = i.company_id AND u.id = i.unit_id
        WHERE l.company_id = ? AND d.status = 'posted'
          AND d.doc_type IN ('opening', 'receipt')
        ORDER BY d.doc_date DESC, d.id DESC, l.line_no
        """,
        (company_id,),
    )
    return [ReceiptLineChoice(**dict(r)) for r in rows]


def list_inventory_documents(
    conn: sqlite3.Connection, company_id: int, limit: int = 100
) -> list[InventoryDocumentSummary]:
    """The latest inventory documents with their total amount, newest first."""
    rows = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.doc_type, d.memo, d.status,
               d.gl_document_id,
               ct.name AS cost_type_name,
               COALESCE(SUM(l.amount), 0) AS amount
        FROM inventory_documents d
        LEFT JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        LEFT JOIN landed_cost_types ct
          ON ct.company_id = d.company_id AND ct.id = d.landed_cost_type_id
        WHERE d.company_id = ?
        GROUP BY d.id
        ORDER BY d.doc_date DESC, d.id DESC
        LIMIT ?
        """,
        (company_id, limit),
    )
    return [InventoryDocumentSummary(**dict(r)) for r in rows]
