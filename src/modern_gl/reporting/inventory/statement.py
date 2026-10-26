"""«Ведомость по складу»: each item on each warehouse over a period — what it had at the
start, what came in, what went out and what is left, in quantity and value — and the
value of the warehouse against the balance of the stock accounts in the books.

Everything is summed in SQL from the posted movements; nothing new is kept."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key
from modern_gl.infrastructure.db import Connection

BY_ITEM, BY_WAREHOUSE = "item", "warehouse"


@dataclass
class Turnover:
    """Quantity and value at the start, in, out and at the end of a period."""

    opening_quantity: int = 0
    opening_amount: int = 0
    in_quantity: int = 0
    in_amount: int = 0
    out_quantity: int = 0
    out_amount: int = 0

    @property
    def closing_quantity(self) -> int:
        return self.opening_quantity + self.in_quantity - self.out_quantity

    @property
    def closing_amount(self) -> int:
        return self.opening_amount + self.in_amount - self.out_amount

    def add(self, other: Turnover) -> None:
        self.opening_quantity += other.opening_quantity
        self.opening_amount += other.opening_amount
        self.in_quantity += other.in_quantity
        self.in_amount += other.in_amount
        self.out_quantity += other.out_quantity
        self.out_amount += other.out_amount


@dataclass
class StatementRow(Turnover):
    """An item or a warehouse (depth 0) and under it the other one (depth 1). A row
    whose lines have different units (a warehouse) has no unit: its quantities mean
    nothing and are not shown."""

    name: str = ""
    item_id: int | None = None
    warehouse_id: int | None = None
    depth: int = 0
    unit_code: str = ""
    precision: int = 0
    is_total: bool = False

    @property
    def has_quantity(self) -> bool:
        return bool(self.unit_code)


@dataclass
class StockStatement:
    rows: list[StatementRow] = field(default_factory=list)
    total: StatementRow = field(default_factory=lambda: StatementRow(is_total=True))
    # Dt − Kt of the stock accounts at the end of the period (the common book); None:
    # no item yet, nothing to compare
    books_amount: int | None = None


def _turnovers(
    conn: Connection, company_id: int, date_from: str, date_to: str
) -> list[tuple[dict, Turnover]]:
    rows = conn.execute(
        """
        SELECT m.item_id, m.warehouse_id, iv.code AS item_code, iv.name AS item_name,
               wv.name AS warehouse_name, u.code AS unit_code, u.precision,
               SUM(CASE WHEN m.doc_date < :f THEN m.quantity ELSE 0 END) AS oq,
               SUM(CASE WHEN m.doc_date < :f THEN m.amount ELSE 0 END) AS oa,
               SUM(CASE WHEN m.doc_date >= :f AND m.quantity > 0
                        THEN m.quantity ELSE 0 END) AS iq,
               SUM(CASE WHEN m.doc_date >= :f AND m.amount > 0
                        THEN m.amount ELSE 0 END) AS ia,
               SUM(CASE WHEN m.doc_date >= :f AND m.quantity < 0
                        THEN -m.quantity ELSE 0 END) AS xq,
               SUM(CASE WHEN m.doc_date >= :f AND m.amount < 0
                        THEN -m.amount ELSE 0 END) AS xa
        FROM stock_movements m
        JOIN inventory_documents d
          ON d.company_id = m.company_id AND d.id = m.document_id AND d.status = 'posted'
        JOIN inventory_items i ON i.company_id = m.company_id AND i.id = m.item_id
        JOIN subconto_values iv ON iv.id = i.subconto_value_id
        JOIN inventory_units u ON u.id = i.unit_id
        JOIN warehouses w ON w.company_id = m.company_id AND w.id = m.warehouse_id
        JOIN subconto_values wv ON wv.id = w.subconto_value_id
        WHERE m.company_id = :c AND m.doc_date <= :t
        GROUP BY m.item_id, m.warehouse_id, iv.code, iv.name, wv.name, u.code, u.precision
        """,
        {"c": company_id, "f": date_from, "t": date_to},
    ).fetchall()
    result = []
    for r in rows:
        turnover = Turnover(r["oq"], r["oa"], r["iq"], r["ia"], r["xq"], r["xa"])
        if any(vars(turnover).values()):
            result.append((dict(r), turnover))
    return result


def _item_name(r: dict) -> str:
    return f"{r['item_code']} {r['item_name']}" if r["item_code"] else r["item_name"]


def stock_statement(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    by: str = BY_ITEM,
) -> StockStatement:
    """By item (each item, its warehouses under it when it is on more than one) or by
    warehouse (each warehouse, its items under it). A transfer is out of one warehouse
    and into another, so it is in both columns of the item's total as well."""
    statement = StockStatement()
    lines = _turnovers(conn, company_id, iso_date(date_from), iso_date(date_to))
    parent_key = "item_id" if by == BY_ITEM else "warehouse_id"
    parents: dict[int, tuple[StatementRow, list[StatementRow]]] = {}
    for r, turnover in lines:
        if r[parent_key] not in parents:
            parent = StatementRow(
                name=_item_name(r) if by == BY_ITEM else r["warehouse_name"],
                **{parent_key: r[parent_key]},
            )
            if by == BY_ITEM:
                parent.unit_code, parent.precision = r["unit_code"], r["precision"]
            parents[r[parent_key]] = (parent, [])
        parent, children = parents[r[parent_key]]
        parent.add(turnover)
        statement.total.add(turnover)
        child = StatementRow(
            name=r["warehouse_name"] if by == BY_ITEM else _item_name(r),
            item_id=r["item_id"],
            warehouse_id=r["warehouse_id"],
            depth=1,
            unit_code=r["unit_code"],
            precision=r["precision"],
            **vars(turnover),
        )
        children.append(child)
    for parent, children in sorted(parents.values(), key=lambda p: sort_key(p[0].name)):
        statement.rows.append(parent)
        if by == BY_WAREHOUSE or len(children) > 1:
            statement.rows.extend(sorted(children, key=lambda c: sort_key(c.name)))
        elif by == BY_ITEM:  # one warehouse: the item's row is that warehouse's
            parent.warehouse_id = children[0].warehouse_id
    statement.books_amount = stock_accounts_balance(conn, company_id, iso_date(date_to))
    return statement


def stock_accounts_balance(conn: Connection, company_id: int, day: str) -> int | None:
    """Dt − Kt at the end of the day of the accounts the items are kept on (posted, the
    common book) — what the warehouse's value should be in the books."""
    accounts = [
        row["inventory_account_id"]
        for row in conn.execute(
            "SELECT DISTINCT inventory_account_id FROM inventory_items WHERE company_id = ?",
            (company_id,),
        )
    ]
    if not accounts:
        return None
    marks = ", ".join("?" for _ in accounts)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE WHEN p.debit_account_id IN ({marks})
                                 THEN p.amount ELSE 0 END), 0)
             - COALESCE(SUM(CASE WHEN p.credit_account_id IN ({marks})
                                 THEN p.amount ELSE 0 END), 0) AS balance
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        WHERE p.company_id = ? AND d.doc_date <= ?
          AND (p.debit_account_id IN ({marks}) OR p.credit_account_id IN ({marks}))
        """,
        (*accounts, *accounts, company_id, day, *accounts, *accounts),
    ).fetchone()
    return row["balance"]
