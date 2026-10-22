"""What each line of an e-qaimə would become: as last time from this counterparty, an
item of the same name, or nothing yet."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from modern_gl.application.eqaime_import.parsing import RETURN_KINDS, EInvoice, EInvoiceLine
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection, Row


@dataclass
class LinePlan:
    line: EInvoiceLine
    item_id: int | None = None
    account_id: int | None = None  # a purchase line without an item: where it goes
    subconto: tuple[int | None, ...] = ()
    found: str = ""  # how it was found: "history", "name", "" (the user chooses)


@dataclass
class InvoicePlan:
    invoice: EInvoice
    counterparty_id: int | None  # None: made from the VÖEN and name when imported
    existing: int | None = None  # the number of a document that has this e-qaimə already
    lines: list[LinePlan] = field(default_factory=list)
    skip_reason: str = ""
    # a purchase's services of an earlier month (D65): the last day of that month
    expense_date: str | None = None

    @property
    def importable(self) -> bool:
        return self.existing is None and not self.skip_reason

    @property
    def has_expenses(self) -> bool:
        """A purchase with a line that is no item (a service, a fixed asset, an expense):
        its expense may belong to an earlier month (D65)."""
        return not self.invoice.outgoing and any(p.item_id is None for p in self.lines)

    @property
    def unresolved(self) -> int:
        """Lines the user has to decide: a purchase line neither an item nor an account,
        a sale's goods line without an item."""
        if self.invoice.outgoing:
            return sum(1 for p in self.lines if p.item_id is None and not p.line.service)
        return sum(1 for p in self.lines if p.item_id is None and p.account_id is None)


def plan_import(
    conn: Connection, company_id: int, invoices: Sequence[EInvoice]
) -> list[InvoicePlan]:
    """What each e-qaimə would become, before anything is written."""
    items = {
        fold(row["name"]): row["id"]
        for row in conn.execute(
            "SELECT i.id, v.name FROM inventory_items i "
            "JOIN subconto_values v ON v.id = i.subconto_value_id "
            "WHERE i.company_id = ? AND v.active = 1",
            (company_id,),
        )
    }
    plans = []
    for invoice in invoices:
        counterparty = known_counterparty(conn, company_id, invoice.party_tin, invoice.party_name)
        plan = InvoicePlan(invoice, counterparty)
        existing = conn.execute(
            "SELECT number FROM inventory_documents "
            "WHERE company_id = ? AND doc_type = ? AND invoice = ?",
            (company_id, invoice.doc_type, invoice.number),
        ).fetchone()
        plan.existing = existing["number"] if existing else None
        if invoice.kind in RETURN_KINDS:
            plan.skip_reason = tr("возврат — пока вводится вручную")
        elif any(line.amount < 0 or line.vat < 0 for line in invoice.lines):
            plan.skip_reason = tr("отрицательные суммы — проверьте на портале")
        history = _history(conn, company_id, invoice.doc_type, counterparty)
        for line in invoice.lines:
            plan.lines.append(_line_plan(line, history, items, invoice.outgoing))
        plans.append(plan)
    return plans


def _line_plan(
    line: EInvoiceLine,
    history: Mapping[str, Row],
    items: Mapping[str, int],
    outgoing: bool,
) -> LinePlan:
    key = fold(line.name)
    last = history.get(key)
    if last is not None:
        if last["item_id"] is not None:
            return LinePlan(line, item_id=last["item_id"], found="history")
        if not outgoing and last["cost_account_id"] is not None:
            subconto = (last["cost_sc1"], last["cost_sc2"], last["cost_sc3"])
            return LinePlan(
                line, account_id=last["cost_account_id"], subconto=subconto, found="history"
            )
        if outgoing:
            return LinePlan(line, found="history")  # sold as a service last time
    if not line.service and key in items:
        return LinePlan(line, item_id=items[key], found="name")
    return LinePlan(line)


def known_counterparty(
    conn: Connection, company_id: int, tax_id: str, name: str = ""
) -> int | None:
    """The company's counterparty with this VÖEN; one without a VÖEN (a non-resident,
    a person) by exactly the same name."""
    if tax_id:
        row = conn.execute(
            "SELECT v.id FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id "
            "WHERE v.company_id = ? AND k.code = 'counterparty' AND v.tax_id = ? "
            "ORDER BY v.active DESC, v.id LIMIT 1",
            (company_id, tax_id),
        ).fetchone()
        return row["id"] if row else None
    if not name.strip():
        return None
    wanted = fold(" ".join(name.split()))
    for row in conn.execute(
        "SELECT v.id, v.name FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id "
        "WHERE v.company_id = ? AND k.code = 'counterparty' AND v.tax_id IS NULL "
        "AND v.is_group = 0 ORDER BY v.active DESC, v.id",
        (company_id,),
    ):
        if fold(" ".join(row["name"].split())) == wanted:
            return row["id"]
    return None


def _history(
    conn: Connection, company_id: int, doc_type: str, counterparty: int | None
) -> dict[str, Row]:
    """What each line name of this counterparty became the last time: memo -> line."""
    if counterparty is None:
        return {}
    result: dict[str, Row] = {}
    for row in conn.execute(
        """
        SELECT l.memo, l.item_id, l.cost_account_id, l.cost_sc1, l.cost_sc2, l.cost_sc3
        FROM inventory_lines l JOIN inventory_documents d ON d.id = l.document_id
        WHERE l.company_id = ? AND d.doc_type = ? AND l.memo <> ''
          AND ? IN (l.offset_sc1, l.offset_sc2, l.offset_sc3)
        ORDER BY d.doc_date, d.id
        """,
        (company_id, doc_type, counterparty),
    ):
        result[fold(row["memo"])] = row  # the latest wins
    return result
