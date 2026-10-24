"""Lists a cell offers: items, warehouses, units, cost types, stock accounts, received lines."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.inventory.model import INCOMING_SQL
from modern_gl.infrastructure.db import Connection


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
    document_id: int = 0
    warehouse_name: str = ""
    memo: str = ""  # of the receipt document
    unit: str = ""


def item_name(conn: Connection, company_id: int, item_id: int) -> str:
    """The name of an item ("" if the company has no such item)."""
    row = conn.execute(
        """
        SELECT v.name
        FROM inventory_items i
        JOIN subconto_values v ON v.company_id = i.company_id AND v.id = i.subconto_value_id
        WHERE i.company_id = ? AND i.id = ?
        """,
        (company_id, item_id),
    ).fetchone()
    return row["name"] if row else ""


def item_choices(conn: Connection, company_id: int) -> list[ItemChoice]:
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


def warehouse_choices(conn: Connection, company_id: int) -> list[Choice]:
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


def unit_choices(conn: Connection, company_id: int) -> list[Choice]:
    """Active units of measure, by name."""
    rows = conn.execute(
        "SELECT id, code, name FROM inventory_units WHERE company_id = ? AND active = 1 "
        "ORDER BY name",
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def landed_cost_type_choices(conn: Connection, company_id: int) -> list[Choice]:
    """Active kinds of additional costs, by name."""
    rows = conn.execute(
        "SELECT id, code, name FROM landed_cost_types "
        "WHERE company_id = ? AND active = 1 ORDER BY name",
        (company_id,),
    )
    return [Choice(r["id"], code_label(r["code"], r["name"])) for r in rows]


def stock_account_choices(conn: Connection, company_id: int) -> list[Choice]:
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


def has_units(conn: Connection, company_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM inventory_units WHERE company_id = ? LIMIT 1", (company_id,)
        ).fetchone()
        is not None
    )


def receipt_line_choices(conn: Connection, company_id: int) -> list[ReceiptLineChoice]:
    """Posted opening and receipt lines, newest first."""
    rows = conn.execute(
        f"""
        SELECT l.id, d.doc_date, d.number, v.name AS item_name, l.quantity, l.amount,
               u.precision, d.id AS document_id, wv.name AS warehouse_name, d.memo,
               u.code AS unit
        FROM inventory_lines l
        JOIN inventory_documents d ON d.company_id = l.company_id AND d.id = l.document_id
        JOIN inventory_items i ON i.company_id = l.company_id AND i.id = l.item_id
        JOIN subconto_values v ON v.company_id = i.company_id AND v.id = i.subconto_value_id
        JOIN inventory_units u ON u.company_id = i.company_id AND u.id = i.unit_id
        JOIN warehouses w ON w.company_id = l.company_id AND w.id = l.warehouse_id
        JOIN subconto_values wv ON wv.company_id = w.company_id AND wv.id = w.subconto_value_id
        WHERE l.company_id = ? AND d.status = 'posted'
          AND d.doc_type IN {INCOMING_SQL}
        ORDER BY d.doc_date DESC, d.id DESC, l.line_no
        """,
        (company_id,),
    )
    return [ReceiptLineChoice(**dict(r)) for r in rows]
