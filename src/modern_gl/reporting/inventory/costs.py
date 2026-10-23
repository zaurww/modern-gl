"""Where an item's cost came from: the receipts and their landed costs, per batch."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class CostSource:
    """A GL posting that can be taken as an expense of a batch (a broker's or customs
    invoice): what is left of it after other «Расходы по партии» documents."""

    document_id: int
    line_no: int
    doc_date: str
    number: int
    debit: str
    credit: str
    subconto: str  # the debit side's values, the credit side's if it has none
    memo: str
    amount: int
    used: int
    debit_account_id: int = 0
    debit_subconto: tuple[int | None, int | None, int | None] = (None, None, None)
    debit_class: str | None = None  # an expense posting is what a batch usually takes

    @property
    def left(self) -> int:
        return self.amount - self.used


def allocated_sql(company: str, document: str, line: str) -> str:
    """A subquery: how much of the GL posting `document`, `line` (SQL expressions) posted
    «Расходы по партии» documents took, all but the one of the next parameter (NULL — none
    left out). The picker and the check on posting count it alike."""
    return (
        "(SELECT COALESCE(SUM(c.amount), 0) FROM landed_cost_charges c "
        "JOIN inventory_documents i ON i.id = c.document_id AND i.status = 'posted' "
        f"WHERE c.company_id = {company} AND c.source_document_id = {document} "
        f"AND c.source_line_no = {line} AND c.document_id IS DISTINCT FROM ?)"
    )


def cost_sources(
    conn: Connection,
    company_id: int,
    exclude_document_id: int | None = None,
    *,
    only_left: bool = True,
) -> list[CostSource]:
    """Posted GL postings of the common book, not made by the warehouse, with something
    left to allocate (posted landed cost documents other than `exclude_document_id` count,
    as when posting),
    newest first. `only_left=False`: also those allocated in full."""
    rows = conn.execute(
        f"""
        SELECT p.document_id, p.line_no, d.doc_date, d.number, p.amount,
               p.debit_account_id, p.dt_sc1, p.dt_sc2, p.dt_sc3, da.account_class,
               COALESCE(NULLIF(p.memo, ''), d.memo) AS memo,
               COALESCE(da.code, da.name) AS debit, COALESCE(ca.code, ca.name) AS credit,
               (SELECT string_agg(v.name, ', ') FROM subconto_values v
                WHERE v.id IN (p.dt_sc1, p.dt_sc2, p.dt_sc3)) AS dt_names,
               (SELECT string_agg(v.name, ', ') FROM subconto_values v
                WHERE v.id IN (p.ct_sc1, p.ct_sc2, p.ct_sc3)) AS ct_names,
               {allocated_sql("p.company_id", "p.document_id", "p.line_no")} AS used
        FROM postings p
        JOIN documents d ON d.id = p.document_id
        JOIN layers l ON l.id = d.layer_id
        JOIN accounts da ON da.id = p.debit_account_id
        JOIN accounts ca ON ca.id = p.credit_account_id
        WHERE p.company_id = ? AND d.status = 'posted' AND l.code = 'common' AND p.amount > 0
          AND NOT EXISTS (SELECT 1 FROM document_owners o
                          WHERE o.company_id = d.company_id AND o.document_id = d.id
                            AND o.module = 'inventory' AND o.role = 'made')
        ORDER BY d.doc_date DESC, d.number DESC, p.line_no
        """,
        (exclude_document_id, company_id),
    )
    return [
        CostSource(
            r["document_id"],
            r["line_no"],
            r["doc_date"],
            r["number"],
            r["debit"],
            r["credit"],
            r["dt_names"] or r["ct_names"] or "",
            r["memo"],
            r["amount"],
            r["used"],
            r["debit_account_id"],
            (r["dt_sc1"], r["dt_sc2"], r["dt_sc3"]),
            r["account_class"],
        )
        for r in rows
        if r["amount"] > r["used"] or not only_left
    ]


@dataclass(frozen=True)
class BatchCharge:
    """An expense of a batch, a column of the batch cost report."""

    id: int
    title: str  # the cost type, else the comment, else the account
    amount: int
    currency: str | None = None
    currency_amount: int | None = None
    rate: int | None = None  # millionths of a manat per unit


@dataclass(frozen=True)
class BatchCostLine:
    """A receipt line of a batch: what it cost and what each expense added."""

    line_id: int
    number: int
    doc_date: str
    item_name: str
    warehouse_name: str
    quantity: int
    precision: int
    unit: str
    cost: int  # the receipt amount in manat
    currency: str | None
    currency_amount: int | None
    rate: int | None
    shares: dict[int, int]  # charge id -> its share of this line

    @property
    def expenses(self) -> int:
        return sum(self.shares.values())

    @property
    def total(self) -> int:
        return self.cost + self.expenses


def batch_cost(
    conn: Connection, company_id: int, document_id: int
) -> tuple[list[BatchCharge], list[BatchCostLine]]:
    """«Себестоимость партии» of a posted batch document: its charges and its lines with
    the receipt price (in a currency and at what rate), each expense and the total."""
    charges = [
        BatchCharge(
            r["id"],
            r["type_name"] or r["memo"] or r["account"] or "",
            r["amount"],
            r["currency"],
            r["currency_amount"],
            r["currency_rate"],
        )
        for r in conn.execute(
            """
            SELECT c.id, c.amount, c.memo, c.currency_amount, c.currency_rate,
                   t.name AS type_name, cur.code AS currency,
                   COALESCE(a.code || '  ' || a.name, a.name) AS account
            FROM landed_cost_charges c
            LEFT JOIN landed_cost_types t ON t.id = c.cost_type_id
            LEFT JOIN currencies cur ON cur.id = c.currency_id
            LEFT JOIN accounts a ON a.id = c.account_id
            WHERE c.company_id = ? AND c.document_id = ?
            ORDER BY c.line_no
            """,
            (company_id, document_id),
        )
    ]
    shares: dict[int, dict[int, int]] = {}
    for r in conn.execute(
        "SELECT line_id, charge_id, amount FROM landed_cost_shares "
        "WHERE company_id = ? AND document_id = ?",
        (company_id, document_id),
    ):
        shares.setdefault(r["line_id"], {})[r["charge_id"]] = r["amount"]
    lines = [
        BatchCostLine(
            r["id"],
            r["number"],
            r["doc_date"],
            r["item_name"],
            r["warehouse_name"],
            r["quantity"],
            r["precision"],
            r["unit"],
            r["amount"],
            r["currency"],
            r["currency_amount"],
            r["currency_rate"],
            shares.get(r["id"], {}),
        )
        for r in conn.execute(
            """
            SELECT lc.id, d.number, d.doc_date, v.name AS item_name, wv.name AS warehouse_name,
                   src.quantity, u.precision, u.code AS unit, src.amount,
                   src.currency_amount, d.currency_rate, cur.code AS currency
            FROM inventory_lines lc
            JOIN inventory_lines src ON src.id = lc.source_receipt_line_id
            JOIN inventory_documents d ON d.id = src.document_id
            JOIN inventory_items i ON i.id = src.item_id
            JOIN subconto_values v ON v.id = i.subconto_value_id
            JOIN inventory_units u ON u.id = i.unit_id
            JOIN warehouses w ON w.id = src.warehouse_id
            JOIN subconto_values wv ON wv.id = w.subconto_value_id
            LEFT JOIN currencies cur ON cur.id = d.currency_id
            WHERE lc.company_id = ? AND lc.document_id = ?
            ORDER BY lc.line_no
            """,
            (company_id, document_id),
        )
    ]
    return charges, lines
