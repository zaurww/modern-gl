"""«Əlavə xərclər» by declaration: what a receipt's goods cost by the supplier's invoice
(or the customs declaration), what each kind of expense added and by how many percent.

A receipt is shown when it is a customs declaration or has landed costs. Its expenses
are all posted «Расходы по партии» documents on it, whatever their date: the report is
the full cost of the declaration, as it stands now."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.domain.money import round_ratio
from modern_gl.infrastructure.db import Connection


def percent_added(expenses: int, cost: int) -> int | None:
    """How much the expenses added to the cost, in hundredths of a percent."""
    return round_ratio(expenses * 10_000, cost) if cost else None


@dataclass(frozen=True)
class LandedLine:
    """A receipt line: its price, each kind of expense and what it costs with them."""

    line_id: int
    item_name: str
    unit: str
    precision: int
    quantity: int  # thousandths
    currency_amount: int | None
    cost: int  # the receipt amount in manat
    expenses: dict[str, int] = field(default_factory=dict)  # kind of expense -> share

    @property
    def added(self) -> int:
        return sum(self.expenses.values())

    @property
    def total(self) -> int:
        return self.cost + self.added

    @property
    def percent(self) -> int | None:
        return percent_added(self.added, self.cost)


@dataclass(frozen=True)
class Declaration:
    """A receipt (a customs declaration or an e-qaimə) with its lines; the expense
    documents that went on it."""

    receipt_id: int
    number: int
    doc_date: str
    invoice: str
    invoice_kind: str
    supplier: str
    currency: str | None
    rate: int | None  # millionths of a manat per unit
    lines: list[LandedLine] = field(default_factory=list)
    expense_documents: list[tuple[int, int, str]] = field(default_factory=list)  # id, №, date

    @property
    def cost(self) -> int:
        return sum(line.cost for line in self.lines)

    @property
    def currency_amount(self) -> int | None:
        if self.currency is None:
            return None
        return sum(line.currency_amount or 0 for line in self.lines)

    @property
    def expenses(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for line in self.lines:
            for kind, amount in line.expenses.items():
                result[kind] = result.get(kind, 0) + amount
        return result

    @property
    def added(self) -> int:
        return sum(line.added for line in self.lines)

    @property
    def total(self) -> int:
        return self.cost + self.added

    @property
    def percent(self) -> int | None:
        return percent_added(self.added, self.cost)


def landed_cost_report(
    conn: Connection, company_id: int, date_from: str, date_to: str
) -> tuple[list[str], list[Declaration]]:
    """The kinds of expense (the report's columns, in the order of their directory) and
    the receipts of the period with landed costs or on a customs declaration, by date."""
    shares, kinds = _shares(conn, company_id, date_from, date_to)
    declarations: dict[int, Declaration] = {}
    for r in conn.execute(
        """
        SELECT d.id AS receipt_id, d.number, d.doc_date, d.invoice, d.invoice_kind,
               d.currency_rate, cur.code AS currency,
               (SELECT c.name FROM inventory_line_counterparties c
                WHERE c.company_id = d.company_id AND c.document_id = d.id
                ORDER BY c.line_no, c.counterparty_id LIMIT 1) AS supplier,
               l.id, v.name AS item_name, u.code AS unit, u.precision, l.quantity,
               l.amount, l.currency_amount
        FROM inventory_documents d
        JOIN inventory_lines l ON l.document_id = d.id
        JOIN inventory_items i ON i.id = l.item_id
        JOIN subconto_values v ON v.id = i.subconto_value_id
        JOIN inventory_units u ON u.id = i.unit_id
        LEFT JOIN currencies cur ON cur.id = d.currency_id
        WHERE d.company_id = ? AND d.doc_type = 'receipt' AND d.status = 'posted'
          AND d.doc_date BETWEEN ? AND ?
          AND (d.invoice_kind = 'customs' OR d.id IN (
                SELECT src.document_id FROM inventory_lines src
                JOIN inventory_lines lc ON lc.source_receipt_line_id = src.id
                JOIN landed_cost_shares s ON s.line_id = lc.id
                WHERE src.company_id = d.company_id))
        ORDER BY d.doc_date, d.number, l.line_no
        """,
        (company_id, date_from, date_to),
    ):
        declaration = declarations.get(r["receipt_id"])
        if declaration is None:
            declaration = declarations[r["receipt_id"]] = Declaration(
                r["receipt_id"],
                r["number"],
                r["doc_date"],
                r["invoice"] or "",
                r["invoice_kind"] or "",
                r["supplier"] or "",
                r["currency"],
                r["currency_rate"],
            )
        declaration.lines.append(
            LandedLine(
                r["id"],
                r["item_name"],
                r["unit"],
                r["precision"],
                r["quantity"],
                r["currency_amount"],
                r["amount"],
                shares.get(r["id"], {}),
            )
        )
    _attach_documents(conn, company_id, declarations)
    return kinds, list(declarations.values())


def _shares(
    conn: Connection, company_id: int, date_from: str, date_to: str
) -> tuple[dict[int, dict[str, int]], list[str]]:
    """Receipt line -> kind of expense -> its share, and the kinds in directory order (a
    charge without a kind is named by its comment or account, after the kinds)."""
    shares: dict[int, dict[str, int]] = {}
    order: dict[str, tuple[int, str]] = {}
    for r in conn.execute(
        """
        SELECT lc.source_receipt_line_id AS line_id, t.id AS kind_id,
               COALESCE(t.name, NULLIF(c.memo, ''), a.code, a.name, '') AS kind,
               SUM(s.amount) AS amount
        FROM landed_cost_shares s
        JOIN inventory_documents e ON e.id = s.document_id AND e.status = 'posted'
        JOIN landed_cost_charges c ON c.id = s.charge_id
        JOIN inventory_lines lc ON lc.id = s.line_id
        JOIN inventory_lines src ON src.id = lc.source_receipt_line_id
        JOIN inventory_documents d ON d.id = src.document_id
        LEFT JOIN landed_cost_types t ON t.id = c.cost_type_id
        LEFT JOIN accounts a ON a.id = c.account_id
        WHERE s.company_id = ? AND d.doc_date BETWEEN ? AND ?
        GROUP BY lc.source_receipt_line_id, t.id,
                 COALESCE(t.name, NULLIF(c.memo, ''), a.code, a.name, '')
        """,
        (company_id, date_from, date_to),
    ):
        kinds = shares.setdefault(r["line_id"], {})
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["amount"]
        rank = r["kind_id"] if r["kind_id"] is not None else 1 << 62
        order[r["kind"]] = min(order.get(r["kind"], (rank, r["kind"])), (rank, r["kind"]))
    return shares, sorted(order, key=lambda kind: order[kind])


def _attach_documents(conn: Connection, company_id: int, declarations: dict[int, Declaration]):
    if not declarations:
        return
    for r in conn.execute(
        """
        SELECT DISTINCT src.document_id AS receipt_id, e.id, e.number, e.doc_date
        FROM inventory_documents e
        JOIN inventory_lines lc ON lc.document_id = e.id
        JOIN inventory_lines src ON src.id = lc.source_receipt_line_id
        WHERE e.company_id = ? AND e.doc_type = 'landed_cost' AND e.status = 'posted'
        ORDER BY e.doc_date, e.number
        """,
        (company_id,),
    ):
        declaration = declarations.get(r["receipt_id"])
        if declaration is not None:
            declaration.expense_documents.append((r["id"], r["number"], r["doc_date"]))
