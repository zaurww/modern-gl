"""The plans as purchase and sale drafts: lines, warehouse, settlement account."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from modern_gl.application.common import pad_subconto
from modern_gl.application.eqaime.counterparties import (
    add_counterparties,
    new_counterparties,
    remember_legal_names,
)
from modern_gl.application.eqaime.planning import InvoicePlan, LinePlan
from modern_gl.application.inventory import (
    QUANTITY_SCALE,
    STANDARD_VAT_RATE,
    Inventory,
    ReceiptLine,
    ReturnLine,
    SaleLine,
)
from modern_gl.application.queries import remembered_sale_subconto
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, transaction


def import_drafts(
    inventory: Inventory,
    company_id: int,
    plans: Sequence[InvoicePlan],
    names: Mapping[str, str] | None = None,
) -> list[int]:
    """Write the importable plans as drafts in one transaction; the new drafts. Missing
    counterparties are added first, once per VÖEN, under `names` (key -> name) or a
    shortened portal name; the settlement account is the one of its type (60 / 62).
    A plan with `attach_to` is written into that waiting purchase instead (D119): its
    number, and its VAT when the amounts agree."""
    ledger = inventory.ledger
    conn = inventory.conn
    chosen = [plan for plan in plans if plan.importable]
    created = []
    with transaction(conn):
        parties = new_counterparties(chosen)
        for party in parties:
            party.name = (names or {}).get(party.key, party.name)
        add_counterparties(ledger, company_id, parties, chosen)
        remember_legal_names(ledger, company_id, chosen)
        kind = ledger.subconto_kind_id(company_id, "counterparty")
        warehouse = _only_warehouse(conn, company_id)
        for plan in chosen:
            invoice = plan.invoice
            if plan.attach_to is not None:
                vat = invoice.vat if plan.agrees(plan.attach_to) else None
                inventory.attach_invoice(
                    company_id, plan.attach_to.document_id, invoice.number, vat
                )
                continue
            assert plan.counterparty_id is not None  # added above
            if plan.return_type is not None:
                created.append(_return_draft(inventory, company_id, plan, warehouse, kind))
                continue
            account = _settlement_account(conn, company_id, invoice.outgoing)
            subconto = _place(conn, company_id, account, kind, plan.counterparty_id)
            vat_rate = STANDARD_VAT_RATE if invoice.vat else None
            if invoice.outgoing:
                created.append(
                    inventory.create_sale_draft(
                        company_id,
                        invoice.doc_date,
                        [
                            _sale_line(conn, company_id, p, warehouse, plan.counterparty_id)
                            for p in plan.lines
                        ],
                        account,
                        subconto,
                        tr("Продажа по e-qaimə {n}", n=invoice.number),
                        vat_rate=vat_rate,
                        invoice=invoice.number,
                    )
                )
            else:
                created.append(
                    inventory.create_receipt_draft(
                        company_id,
                        invoice.doc_date,
                        [_receipt_line(conn, p, warehouse, plan.expense_date) for p in plan.lines],
                        account,
                        subconto,
                        tr("Покупка по e-qaimə {n}", n=invoice.number),
                        vat_rate=vat_rate,
                        invoice=invoice.number,
                    )
                )
    return created


def _return_draft(
    inventory: Inventory, company_id: int, plan: InvoicePlan, warehouse: int | None, kind: int
) -> int:
    """A return e-qaimə as a return draft: the customer's account (receivable) for goods
    back from a customer, the supplier's (payable) for goods back to the supplier."""
    conn, invoice = inventory.conn, plan.invoice
    assert plan.counterparty_id is not None and plan.return_type is not None
    account = _settlement_account(conn, company_id, plan.as_sale)
    return inventory.create_return_draft(
        company_id,
        invoice.doc_date,
        plan.return_type,
        [
            ReturnLine(
                p.item_id,
                warehouse,
                _quantity(conn, p.item_id, p.line.quantity),
                _amount(p.line.amount),
                _amount(p.line.vat, zero=True),
                p.line.name,
            )
            for p in plan.lines
        ],
        account,
        _place(conn, company_id, account, kind, plan.counterparty_id),
        tr("Возврат по e-qaimə {n}", n=invoice.number),
        vat_rate=STANDARD_VAT_RATE if invoice.vat else None,
        invoice=invoice.number,
    )


def _receipt_line(
    conn: Connection, plan: LinePlan, warehouse: int | None, expense_date: str | None
) -> ReceiptLine:
    """`expense_date`: the month the purchase's services belong to (D65), the goods none."""
    line = plan.line
    goods = plan.item_id is not None
    return ReceiptLine(
        plan.item_id,
        warehouse if goods else None,
        _quantity(conn, plan.item_id, line.quantity),
        _amount(line.amount),
        line.name,
        vat_amount=_amount(line.vat, zero=True),
        expense_account_id=None if goods else plan.account_id,
        expense_subconto=() if goods else plan.subconto,
        expense_date=None if goods else expense_date,
    )


def _sale_line(
    conn: Connection,
    company_id: int,
    plan: LinePlan,
    warehouse: int | None,
    counterparty: int,
) -> SaleLine:
    """A sale line; its sales group and the like (D61) as the item (the service) had the
    last time it was sold."""
    line = plan.line
    goods = plan.item_id is not None
    return SaleLine(
        plan.item_id,
        warehouse if goods else None,
        _quantity(conn, plan.item_id, line.quantity),
        _amount(line.amount),
        _amount(line.vat, zero=True),
        line.name,
        sale_subconto=remembered_sale_subconto(
            conn, company_id, plan.item_id, line.name, counterparty
        ),
    )


def _amount(minor: int, zero: bool = False) -> Decimal | None:
    if minor == 0 and not zero:
        return None  # a draft may lack it; posting asks for it
    return from_minor(minor)


def _quantity(conn: Connection, item_id: int | None, quantity: Decimal | None) -> Decimal | None:
    """The quantity if the item's unit (or a service: 6 digits) takes it, else none: the
    user types it (the e-qaimə's unit may differ from the item's)."""
    if quantity is None or quantity <= 0:
        return None
    precision = QUANTITY_SCALE
    if item_id is not None:
        row = conn.execute(
            "SELECT u.precision FROM inventory_items i JOIN inventory_units u ON u.id = i.unit_id "
            "WHERE i.id = ?",
            (item_id,),
        ).fetchone()
        precision = row["precision"]
    step = Decimal(1).scaleb(-precision)
    return quantity if quantity == quantity.quantize(step) else None


def _only_warehouse(conn: Connection, company_id: int) -> int | None:
    rows = conn.execute(
        "SELECT w.id FROM warehouses w JOIN subconto_values v ON v.id = w.subconto_value_id "
        "WHERE w.company_id = ? AND v.active = 1 LIMIT 2",
        (company_id,),
    ).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def _settlement_account(conn: Connection, company_id: int, outgoing: bool) -> int | None:
    """The suppliers' (customers') account: of the payable (receivable) type, the one with
    a counterparty subconto first, by code."""
    kind = conn.execute(
        "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = 'counterparty'",
        (company_id,),
    ).fetchone()
    kind_id = kind["id"] if kind else -1
    row = conn.execute(
        "SELECT id FROM accounts WHERE company_id = ? AND account_type = ? "
        "AND is_group = 0 AND active = 1 "
        "ORDER BY (? IN (sc1_kind_id, sc2_kind_id, sc3_kind_id)) DESC, code LIMIT 1",
        (company_id, "receivable" if outgoing else "payable", kind_id),
    ).fetchone()
    return row["id"] if row else None


def _place(
    conn: Connection, company_id: int, account_id: int | None, kind_id: int, value_id: int
) -> tuple[int | None, int | None, int | None]:
    """The counterparty at its kind's position of the account (the contract stays empty)."""
    if account_id is None:
        return (None, None, None)
    account = conn.execute(
        "SELECT sc1_kind_id, sc2_kind_id, sc3_kind_id FROM accounts "
        "WHERE company_id = ? AND id = ?",
        (company_id, account_id),
    ).fetchone()
    return pad_subconto([value_id if k == kind_id else None for k in tuple(account)])
