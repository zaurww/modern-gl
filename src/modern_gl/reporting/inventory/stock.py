"""What is in stock: balances, an item's card and details, the groups of items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from modern_gl.application.attention import Attention, attention_source
from modern_gl.application.common import group_path
from modern_gl.application.inventory.amounts import unit_price
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure.db import Connection, Row


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
    min_quantity: int | None = None  # the minimum stock (millionths), None — none
    precision: int = 3  # of its unit


@dataclass(frozen=True)
class MovementSource:
    """Where goods came from or went to: the document's kind and what names it — the
    e-qaimə or the customs declaration, the supplier or customer, the other warehouse of a
    transfer, the kind of expense."""

    doc_type: str
    movement_type: str
    invoice: str | None = None
    invoice_kind: str | None = None  # 'customs': a declaration (YGB), not an e-qaimə
    counterparty: str | None = None
    other_warehouse: str | None = None
    cost_type: str | None = None
    incoming_reason: str | None = None  # a mədaxil's (D91)


@dataclass(frozen=True)
class StockSource:
    """The last receipt of an item into a warehouse."""

    doc_date: str
    source: MovementSource


@dataclass(frozen=True)
class StockCardLine:
    doc_date: str
    document_id: int
    number: int
    memo: str
    source: MovementSource
    quantity_in: int
    quantity_out: int
    amount_in: int
    amount_out: int
    quantity_balance: int
    amount_balance: int


def stock_balances(
    conn: Connection,
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


@dataclass(frozen=True)
class BelowMinimum:
    """An item whose stock on all warehouses is under its minimum; what was last paid for
    it, and where it came to (a purchase of what is missing starts from them)."""

    item_id: int
    name: str
    unit_code: str
    precision: int
    quantity: int
    minimum: int
    last_price: int | None  # per unit, minor units
    warehouse_id: int | None

    @property
    def missing(self) -> int:
        return self.minimum - self.quantity


def below_minimum(conn: Connection, company_id: int, day: str | None = None) -> list[BelowMinimum]:
    """The items under their minimum stock (posted documents up to `day`), by name."""
    rows = conn.execute(
        """
        SELECT i.id, v.name, u.code AS unit_code, u.precision, i.min_quantity,
               COALESCE((
                   SELECT SUM(m.quantity) FROM stock_movements m
                   JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
                   WHERE m.company_id = i.company_id AND m.item_id = i.id
                     AND (:day IS NULL OR m.doc_date <= :day)
               ), 0) AS quantity
        FROM inventory_items i
        JOIN subconto_values v ON v.id = i.subconto_value_id AND v.active = 1
        JOIN inventory_units u ON u.id = i.unit_id
        WHERE i.company_id = :c AND i.min_quantity IS NOT NULL
        ORDER BY v.name
        """,
        {"c": company_id, "day": day},
    ).fetchall()
    low = [r for r in rows if r["quantity"] < r["min_quantity"]]
    last = _last_purchases(conn, company_id) if low else {}
    return [
        BelowMinimum(
            r["id"], r["name"], r["unit_code"], r["precision"], r["quantity"], r["min_quantity"],
            *last.get(r["id"], (None, None)),
        )
        for r in low
    ]  # fmt: skip


def _last_purchases(conn: Connection, company_id: int) -> dict[int, tuple[int | None, int]]:
    """Each item's last purchase: the price of one unit and the warehouse it came to."""
    rows = conn.execute(
        """
        SELECT item_id, amount, quantity, warehouse_id FROM (
            SELECT l.item_id, l.amount, l.quantity, l.warehouse_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY l.item_id ORDER BY d.doc_date DESC, d.id DESC
                   ) AS place
            FROM inventory_lines l
            JOIN inventory_documents d
              ON d.company_id = l.company_id AND d.id = l.document_id
             AND d.status = 'posted' AND d.doc_type = 'receipt'
            WHERE l.company_id = ? AND l.item_id IS NOT NULL AND l.quantity > 0
        ) latest
        WHERE place = 1
        """,
        (company_id,),
    )
    return {r["item_id"]: (unit_price(r["amount"], r["quantity"]), r["warehouse_id"]) for r in rows}


@attention_source
def items_below_minimum(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """«Bu gün»: goods to buy — under their minimum stock."""
    count = len(below_minimum(conn, company_id, day))
    return [Attention(tr("Товары ниже минимального остатка"), count, ("inventory",))]


def idle_items(conn: Connection, company_id: int) -> list[StockBalance]:
    """Active items with nothing on any warehouse: shown under the stock (with no
    warehouse) so that an item just made is there to open."""
    rows = conn.execute(
        """
        SELECT i.id AS item_id, v.code AS item_code, v.name AS item_name,
               v.id AS item_value_id, u.code AS unit_code, u.precision
        FROM inventory_items i
        JOIN subconto_values v ON v.company_id = i.company_id AND v.id = i.subconto_value_id
        JOIN inventory_units u ON u.company_id = i.company_id AND u.id = i.unit_id
        WHERE i.company_id = ? AND v.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM stock_movements m
              JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
              WHERE m.company_id = i.company_id AND m.item_id = i.id
              GROUP BY m.warehouse_id
              HAVING SUM(m.quantity) <> 0 OR SUM(m.amount) <> 0
          )
        ORDER BY v.name
        """,
        (company_id,),
    ).fetchall()
    paths = group_paths(conn, company_id)
    return [
        StockBalance(
            r["item_id"],
            r["item_code"],
            r["item_name"],
            0,
            "",
            r["unit_code"],
            r["precision"],
            0,
            0,
            paths.get(r["item_value_id"], ""),
            r["item_value_id"],
        )
        for r in rows
    ]


def group_paths(conn: Connection, company_id: int) -> dict[int, str]:
    """For each directory element in a group: its groups, outermost first (D60)."""
    rows = conn.execute(
        "SELECT id, name, parent_id, is_group FROM subconto_values WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    nodes = {r["id"]: (r["name"], r["parent_id"]) for r in rows}
    paths = {r["id"]: group_path(r["parent_id"], nodes.get) for r in rows}
    return {value_id: path for value_id, path in paths.items() if path}


def item_details(conn: Connection, company_id: int, value_id: int) -> ItemDetails | None:
    """The item a directory element is, if it is one."""
    row = conn.execute(
        """
        SELECT i.id, i.subconto_value_id, i.unit_id, i.inventory_account_id,
               i.min_quantity, u.precision,
               EXISTS (SELECT 1 FROM inventory_lines l WHERE l.item_id = i.id)
               OR EXISTS (SELECT 1 FROM stock_movements m WHERE m.item_id = i.id) AS used
        FROM inventory_items i JOIN inventory_units u ON u.id = i.unit_id
        WHERE i.company_id = ? AND i.subconto_value_id = ?
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
        row["min_quantity"],
        row["precision"],
    )


# what names a movement's source; with MOVEMENT_JOINS over stock_movements m and
# inventory_documents d
MOVEMENT_SOURCE = """
    d.doc_type, m.movement_type, d.invoice, d.invoice_kind, d.incoming_reason,
    (SELECT c.name FROM inventory_line_counterparties c
     WHERE c.company_id = m.company_id AND c.line_id = l.id
     ORDER BY c.counterparty_id LIMIT 1) AS counterparty,
    (SELECT wv.name FROM warehouses w JOIN subconto_values wv ON wv.id = w.subconto_value_id
     WHERE w.company_id = m.company_id AND w.id = CASE m.movement_type
         WHEN 'transfer_in' THEN l.warehouse_id WHEN 'transfer_out' THEN l.to_warehouse_id
     END) AS other_warehouse,
    COALESCE(ct.name, (
        SELECT string_agg(t.name, ', ') FROM landed_cost_charges c
        JOIN landed_cost_types t ON t.id = c.cost_type_id
        WHERE c.document_id = d.id
    )) AS cost_type
"""
MOVEMENT_JOINS = """
    LEFT JOIN inventory_lines l ON l.company_id = m.company_id AND l.id = m.line_id
    LEFT JOIN landed_cost_types ct
      ON ct.company_id = d.company_id AND ct.id = d.landed_cost_type_id
"""


def movement_source(row: Row) -> MovementSource:
    return MovementSource(
        row["doc_type"],
        row["movement_type"],
        row["invoice"],
        row["invoice_kind"],
        row["counterparty"],
        row["other_warehouse"],
        row["cost_type"],
        row["incoming_reason"],
    )


def last_receipts(conn: Connection, company_id: int) -> dict[tuple[int, int], StockSource]:
    """For each item and warehouse: where its goods last came from (posted movements in)."""
    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT m.item_id, m.warehouse_id, m.doc_date, {MOVEMENT_SOURCE},
                   ROW_NUMBER() OVER (
                       PARTITION BY m.item_id, m.warehouse_id
                       ORDER BY m.doc_date DESC, m.id DESC
                   ) AS place
            FROM stock_movements m
            JOIN inventory_documents d ON d.id = m.document_id
            {MOVEMENT_JOINS}
            WHERE m.company_id = ? AND d.status = 'posted' AND m.quantity > 0
        ) latest
        WHERE place = 1
        """,
        (company_id,),
    ).fetchall()
    return {
        (row["item_id"], row["warehouse_id"]): StockSource(row["doc_date"], movement_source(row))
        for row in rows
    }


def stock_card(
    conn: Connection,
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
        SELECT m.doc_date, d.id AS document_id, d.number, d.memo, {MOVEMENT_SOURCE},
               m.quantity, m.amount, m.id
        FROM stock_movements m
        JOIN inventory_documents d ON d.id = m.document_id
        {MOVEMENT_JOINS}
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
                row["memo"],
                movement_source(row),
                max(row["quantity"], 0),
                max(-row["quantity"], 0),
                max(row["amount"], 0),
                max(-row["amount"], 0),
                quantity_balance,
                amount_balance,
            )
        )
    return result


@attention_source
def negative_stock(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """«Bu gün» (D86): goods that went below zero on a warehouse."""
    count = sum(1 for b in stock_balances(conn, company_id, day) if b.quantity < 0)
    return [Attention(tr("Отрицательный остаток на складе"), count, ("inventory",))]
