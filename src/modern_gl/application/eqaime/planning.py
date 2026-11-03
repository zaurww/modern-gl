"""What each line of an e-qaimə would become: as last time from this counterparty, an
item of the same name, or nothing yet."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from modern_gl.application.counterparties import known_counterparty
from modern_gl.application.eqaime.parsing import RETURN_KINDS, EInvoice, EInvoiceLine
from modern_gl.application.inventory.model import PURCHASE_RETURN, RETURN_TYPES, SALE_RETURN
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection, Row


@dataclass
class LinePlan:
    line: EInvoiceLine
    item_id: int | None = None
    account_id: int | None = None  # a purchase line without an item: where it goes
    subconto: tuple[int | None, ...] = ()
    found: str = ""  # how it was found: "history", "name", "" (the user chooses)


@dataclass(frozen=True)
class AwaitingPurchase:
    """A purchase of the supplier that waits for its e-qaimə (D119)."""

    document_id: int
    number: int
    doc_date: str
    amount: int  # without VAT, the lines of this supplier
    vat: int


@dataclass
class InvoicePlan:
    invoice: EInvoice
    counterparty_id: int | None  # None: made from the VÖEN and name when imported
    existing: int | None = None  # the number of a document that has this e-qaimə already
    lines: list[LinePlan] = field(default_factory=list)
    skip_reason: str = ""
    # a purchase's (sale's) services of an earlier month (D65, D192): the last day of it
    expense_date: str | None = None
    # the supplier's purchases waiting for an e-qaimə (D119), and the one this e-qaimə is
    # written into instead of a new draft (None: a new draft)
    awaiting: list[AwaitingPurchase] = field(default_factory=list)
    attach_to: AwaitingPurchase | None = None

    @property
    def return_type(self) -> str | None:
        """A return e-qaimə («malların geri qaytarılması»): the company's own, sent to its
        supplier — goods back to the supplier; a customer's — goods back from it."""
        if self.invoice.kind not in RETURN_KINDS:
            return None
        return PURCHASE_RETURN if self.invoice.outgoing else SALE_RETURN

    @property
    def document_type(self) -> str:
        return self.return_type or self.invoice.doc_type

    @property
    def as_sale(self) -> bool:
        """Its lines are read as a sale's (a customer's return too), else a purchase's."""
        kind = self.return_type
        return self.invoice.outgoing if kind is None else kind == SALE_RETURN

    @property
    def importable(self) -> bool:
        return self.existing is None and not self.skip_reason

    def agrees(self, purchase: AwaitingPurchase) -> bool:
        """The e-qaimə's amount without VAT is the purchase's: its VAT is taken over."""
        return purchase.amount == self.invoice.amount

    @property
    def has_expenses(self) -> bool:
        """A purchase with a line that is no item (a service, a fixed asset, an expense),
        or a sale with a service line: its expense (income) may belong to an earlier
        month (D65, D192). A return's lines are goods."""
        if self.return_type is not None:
            return False
        if self.invoice.outgoing:
            return any(p.item_id is None and p.line.service for p in self.lines)
        return any(p.item_id is None for p in self.lines)

    @property
    def unresolved(self) -> int:
        """Lines the user has to decide: a purchase line neither an item nor an account,
        a sale's goods line without an item."""
        if self.return_type is not None:  # goods only
            return sum(1 for p in self.lines if p.item_id is None)
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
    awaiting = _awaiting(conn, company_id)
    plans = []
    for invoice in invoices:
        counterparty = known_counterparty(conn, company_id, invoice.party_tin, invoice.party_name)
        plan = InvoicePlan(invoice, counterparty)
        existing = conn.execute(
            "SELECT number FROM inventory_documents "
            "WHERE company_id = ? AND doc_type = ? AND invoice = ?",
            (company_id, plan.document_type, invoice.number),
        ).fetchone()
        plan.existing = existing["number"] if existing else None
        returned = plan.return_type
        if returned and any(line.service for line in invoice.lines):
            plan.skip_reason = tr("возврат услуг — вводится вручную")
        elif any(line.amount < 0 or line.vat < 0 for line in invoice.lines):
            plan.skip_reason = tr("отрицательные суммы — проверьте на портале")
        # a return's lines are what was bought from (sold to) the counterparty
        source = RETURN_TYPES[returned] if returned else invoice.doc_type
        history = _history(conn, company_id, source, counterparty)
        for line in invoice.lines:
            planned = _line_plan(line, history, items, plan.as_sale)
            plan.lines.append(planned if not returned or planned.item_id else LinePlan(line))
        if plan.importable and not returned and not invoice.outgoing and counterparty:
            plan.awaiting = awaiting.get(counterparty, [])
        plans.append(plan)
    _choose_awaiting(plans)
    return plans


def _awaiting(conn: Connection, company_id: int) -> dict[int, list[AwaitingPurchase]]:
    """The purchases waiting for an e-qaimə in the open period, by their supplier
    (a counterparty of their settlement lines), oldest first."""
    result: dict[int, list[AwaitingPurchase]] = {}
    for row in conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, v.counterparty_id,
               SUM(l.amount) AS amount, SUM(l.vat_amount) AS vat
        FROM inventory_documents d
        JOIN companies c ON c.id = d.company_id
        JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        JOIN inventory_line_counterparties v
          ON v.company_id = l.company_id AND v.line_id = l.id
        WHERE d.company_id = ? AND d.awaits_invoice = 1 AND d.currency_id IS NULL
          AND (c.closed_through IS NULL OR d.doc_date > c.closed_through)
        GROUP BY d.id, d.number, d.doc_date, v.counterparty_id
        ORDER BY d.doc_date, d.id
        """,
        (company_id,),
    ):
        result.setdefault(row["counterparty_id"], []).append(
            AwaitingPurchase(row["id"], row["number"], row["doc_date"], row["amount"], row["vat"])
        )
    return result


def _choose_awaiting(plans: Sequence[InvoicePlan]) -> None:
    """Each e-qaimə, oldest first, is written into the supplier's oldest waiting purchase
    of the same amount without VAT that no other e-qaimə took; other amounts are only
    offered — the user chooses."""
    taken: set[int] = set()
    for plan in sorted(plans, key=lambda p: (p.invoice.doc_date, p.invoice.number)):
        for purchase in plan.awaiting:
            if purchase.document_id not in taken and plan.agrees(purchase):
                plan.attach_to = purchase
                taken.add(purchase.document_id)
                break


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
