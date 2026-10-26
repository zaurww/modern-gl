"""«Карточка товара» over a period and «Валовая прибыль по товарам» — what the warehouse
statement and the sales open into. Read from the posted movements and sale lines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.inventory.stock import (
    MOVEMENT_JOINS,
    MOVEMENT_SOURCE,
    MovementSource,
    movement_source,
)

BY_ITEM, BY_CUSTOMER = "item", "customer"


@dataclass(frozen=True)
class CardMovement:
    doc_date: str
    document_id: int
    number: int
    warehouse: str
    source: MovementSource
    quantity: int  # + in, − out
    amount: int
    quantity_balance: int  # after the movement
    amount_balance: int


@dataclass
class ItemCard:
    name: str = ""
    unit_code: str = ""
    precision: int = 0
    opening_quantity: int = 0
    opening_amount: int = 0
    lines: list[CardMovement] = field(default_factory=list)

    @property
    def closing_quantity(self) -> int:
        return self.lines[-1].quantity_balance if self.lines else self.opening_quantity

    @property
    def closing_amount(self) -> int:
        return self.lines[-1].amount_balance if self.lines else self.opening_amount


def item_card(
    conn: Connection,
    company_id: int,
    item_id: int,
    warehouse_id: int | None,
    date_from: date | str,
    date_to: date | str,
) -> ItemCard:
    """The item on one warehouse (or on all, None): the balance before the period, then
    each movement of the period with the balance after it."""
    head = conn.execute(
        """
        SELECT v.code, v.name, u.code AS unit_code, u.precision
        FROM inventory_items i
        JOIN subconto_values v ON v.id = i.subconto_value_id
        JOIN inventory_units u ON u.id = i.unit_id
        WHERE i.company_id = ? AND i.id = ?
        """,
        (company_id, item_id),
    ).fetchone()
    card = ItemCard()
    if head is None:
        return card
    card.name = f"{head['code']} {head['name']}" if head["code"] else head["name"]
    card.unit_code, card.precision = head["unit_code"], head["precision"]
    start, end = iso_date(date_from), iso_date(date_to)
    where = "m.company_id = :c AND m.item_id = :i AND (:w IS NULL OR m.warehouse_id = :w)"
    params = {"c": company_id, "i": item_id, "w": warehouse_id, "f": start, "t": end}
    opening = conn.execute(
        f"""
        SELECT COALESCE(SUM(m.quantity), 0) AS q, COALESCE(SUM(m.amount), 0) AS a
        FROM stock_movements m
        JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
        WHERE {where} AND m.doc_date < :f
        """,
        params,
    ).fetchone()
    card.opening_quantity, card.opening_amount = opening["q"], opening["a"]
    rows = conn.execute(
        f"""
        SELECT m.doc_date, d.id AS document_id, d.number, wv.name AS warehouse,
               {MOVEMENT_SOURCE}, m.quantity, m.amount
        FROM stock_movements m
        JOIN inventory_documents d ON d.id = m.document_id AND d.status = 'posted'
        JOIN warehouses w ON w.company_id = m.company_id AND w.id = m.warehouse_id
        JOIN subconto_values wv ON wv.id = w.subconto_value_id
        {MOVEMENT_JOINS}
        WHERE {where} AND m.doc_date BETWEEN :f AND :t
        ORDER BY m.doc_date, d.id, m.id
        """,
        params,
    ).fetchall()
    quantity, amount = card.opening_quantity, card.opening_amount
    for r in rows:
        quantity += r["quantity"]
        amount += r["amount"]
        card.lines.append(
            CardMovement(
                r["doc_date"],
                r["document_id"],
                r["number"],
                r["warehouse"],
                movement_source(r),
                r["quantity"],
                r["amount"],
                quantity,
                amount,
            )
        )
    return card


@dataclass
class ProfitRow:
    """Sold over a period: revenue without VAT, the cost of the goods and what is left.
    A customer (depth 0, by customer) has its items under it (depth 1)."""

    name: str
    item_id: int | None = None  # None: services, a customer or the total
    depth: int = 0
    unit_code: str = ""
    precision: int = 0
    quantity: int = 0
    revenue: int = 0
    cost: int = 0
    is_total: bool = False

    @property
    def profit(self) -> int:
        return self.revenue - self.cost

    def add(self, other: ProfitRow) -> None:
        self.quantity += other.quantity
        self.revenue += other.revenue
        self.cost += other.cost


def gross_profit(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    by: str = BY_ITEM,
    services: str = "Услуги",
) -> list[ProfitRow]:
    """Posted sales of the period by item (services — one row) or by customer with its
    items under it; the last row is the total. A sale's cost is what it took from stock
    and what expenses of its batch that came later added to it (landed cost)."""
    rows = conn.execute(
        """
        SELECT l.item_id, v.code, v.name, u.code AS unit_code, u.precision,
               COALESCE((SELECT MIN(c.name) FROM inventory_line_counterparties c
                         WHERE c.company_id = l.company_id AND c.line_id = l.id), '') AS customer,
               SUM(l.quantity) AS quantity, SUM(l.amount) AS revenue,
               SUM(l.expense_amount + COALESCE((
                   SELECT SUM(a.amount) FROM landed_cost_expense_allocations a
                   JOIN inventory_documents ld
                     ON ld.id = a.document_id AND ld.status = 'posted'
                   WHERE a.company_id = l.company_id AND a.issue_line_id = l.id), 0)) AS cost
        FROM inventory_lines l
        JOIN inventory_documents d
          ON d.company_id = l.company_id AND d.id = l.document_id
         AND d.doc_type = 'sale' AND d.status = 'posted'
        LEFT JOIN inventory_items i ON i.company_id = l.company_id AND i.id = l.item_id
        LEFT JOIN subconto_values v ON v.id = i.subconto_value_id
        LEFT JOIN inventory_units u ON u.id = i.unit_id
        WHERE l.company_id = ? AND d.doc_date BETWEEN ? AND ?
        GROUP BY l.item_id, v.code, v.name, u.code, u.precision, customer
        """,
        (company_id, iso_date(date_from), iso_date(date_to)),
    ).fetchall()
    total = ProfitRow("", is_total=True)
    groups: dict[str, tuple[ProfitRow, dict[int | None, ProfitRow]]] = {}
    for r in rows:
        line = ProfitRow(
            (f"{r['code']} {r['name']}" if r["code"] else r["name"])
            if r["item_id"] is not None
            else services,
            r["item_id"],
            unit_code=r["unit_code"] or "",
            precision=r["precision"] or 0,
            quantity=r["quantity"] if r["item_id"] is not None else 0,
            revenue=r["revenue"],
            cost=r["cost"],
        )
        total.add(line)
        group = r["customer"] if by == BY_CUSTOMER else ""
        if group not in groups:
            groups[group] = (ProfitRow(group), {})
        head, items = groups[group]
        head.add(line)
        if line.item_id in items:
            items[line.item_id].add(line)
        else:
            items[line.item_id] = line
    result: list[ProfitRow] = []
    for name in sorted(groups, key=sort_key):
        head, items = groups[name]
        ordered = sorted(items.values(), key=lambda r: (r.item_id is None, sort_key(r.name)))
        if by == BY_CUSTOMER:
            result.append(head)
            for row in ordered:
                row.depth = 1
        result.extend(ordered)
    if result:
        result.append(total)
    return result
