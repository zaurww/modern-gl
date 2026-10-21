"""Import of e-qaimə from the tax portal into purchase and sale drafts (D45).

A received e-qaimə becomes a purchase, a sent one a sale; only drafts are made: the user
checks every one by eye and posts it (suppliers write names and codes wrongly).

A line is goods or a service by its code, as etaxes-ext decides: codes «99…» are works
and services (CPA), others goods (ƏMTN). What a line becomes is guessed, in this order:
the same name from the same counterparty last time (its item, or its account and
subconto), an item of the same name, else nothing — a purchase line without an item and
without an account does not post until the user chooses."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from modern_gl.application.common import pad_subconto
from modern_gl.application.inventory import (
    QUANTITY_SCALE,
    STANDARD_VAT_RATE,
    Inventory,
    ReceiptLine,
    SaleLine,
    vat_of,
)
from modern_gl.application.ledger import Ledger
from modern_gl.domain.eqaime import ON_APPROVAL, PortalInvoice, portal_invoice
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import to_minor
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import transaction

PURCHASE, SALE = "receipt", "sale"
# kinds that are not an ordinary sale: a return needs a return document (not made yet)
RETURN_KINDS = {"returnInvoice", "returnByAgent", "returnRecycled"}


@dataclass(frozen=True)
class EInvoiceLine:
    name: str
    code: str
    unit: str
    quantity: Decimal | None
    amount: int  # without VAT (cost + excise), minor units
    vat: int  # 18% of the line's VAT base, minor units

    @property
    def service(self) -> bool:
        """Works and services have codes «99…»; an empty or odd code: unknown, goods."""
        return self.code.isdigit() and self.code.startswith("99")


@dataclass(frozen=True)
class EInvoice:
    portal_id: str
    source_system: str
    number: str
    doc_date: str  # ISO
    outgoing: bool  # sent by the company: a sale
    status: str
    kind: str
    party_tin: str
    party_name: str
    lines: tuple[EInvoiceLine, ...]
    listed: PortalInvoice | None = None  # as the portal's list shows it: kept, reconciled

    @property
    def pending(self) -> bool:
        """Təsdiq gözləyir: not yet approved by the buyer (the list's status first: the
        list was asked for it)."""
        return (self.listed.status if self.listed else self.status) == ON_APPROVAL

    @property
    def doc_type(self) -> str:
        return SALE if self.outgoing else PURCHASE

    @property
    def amount(self) -> int:
        return sum(line.amount for line in self.lines)

    @property
    def vat(self) -> int:
        return sum(line.vat for line in self.lines)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except InvalidOperation:
        return Decimal(0)


def _minor(value: Any) -> int:
    return to_minor(_decimal(value).quantize(Decimal("0.01")))


def parse_invoice(row: Mapping[str, Any], detail: Mapping[str, Any], outgoing: bool) -> EInvoice:
    """An e-qaimə from its list row and its details, as etaxes-ext reads them
    (`buildDetailRows`): the party is the receiver of a sent one, the sender of a received
    one; the VAT is 18% of `vat18` (the API does not give it per line)."""

    def first(*keys: str) -> Any:
        for source in (detail, row):
            for key in keys:
                if source.get(key) not in (None, ""):
                    return source[key]
        return ""

    party_key = "receiver" if outgoing else "sender"
    party = detail.get(party_key) or row.get(party_key) or {}
    created = str(first("createdAt", "creationDate"))
    lines = []
    for item in detail.get("items") or []:
        base = _minor(item.get("vat18"))
        quantity = item.get("quantity")
        lines.append(
            EInvoiceLine(
                str(item.get("productName") or "").strip(),
                str((item.get("productGroup") or {}).get("code") or "").strip(),
                str(item.get("unit") or "").strip(),
                None if quantity in (None, "") else _decimal(quantity),
                _minor(item.get("cost"))
                + _minor(item.get("serviceCost"))
                + _minor(item.get("excise")),
                vat_of(base, STANDARD_VAT_RATE),
            )
        )
    if not lines:  # an e-qaimə without lines: its totals as one line
        lines.append(
            EInvoiceLine("", "", "", None, _minor(first("costWithoutVat")), _minor(first("vat")))
        )
    return EInvoice(
        str(first("id")),
        str(first("sourceSystem") or "avis"),
        normalize_invoice(str(first("serialNumber", "invoiceNumber"))) or "",
        created[:10],
        outgoing,
        str(first("status")),
        str(first("kind")),
        str(party.get("tin") or row.get(f"{party_key}Tin") or "").strip(),
        str(party.get("name") or row.get(f"{party_key}Name") or "").strip(),
        tuple(lines),
        portal_invoice(row, outgoing),
    )


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

    @property
    def importable(self) -> bool:
        return self.existing is None and not self.skip_reason

    @property
    def unresolved(self) -> int:
        """Lines the user has to decide: a purchase line neither an item nor an account,
        a sale's goods line without an item."""
        if self.invoice.outgoing:
            return sum(1 for p in self.lines if p.item_id is None and not p.line.service)
        return sum(1 for p in self.lines if p.item_id is None and p.account_id is None)


def plan_import(
    conn: sqlite3.Connection, company_id: int, invoices: Sequence[EInvoice]
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
        counterparty = _counterparty(conn, company_id, invoice.party_tin, invoice.party_name)
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
    history: Mapping[str, sqlite3.Row],
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


def _counterparty(
    conn: sqlite3.Connection, company_id: int, tax_id: str, name: str = ""
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
    conn: sqlite3.Connection, company_id: int, doc_type: str, counterparty: int | None
) -> dict[str, sqlite3.Row]:
    """What each line name of this counterparty became the last time: memo -> line."""
    if counterparty is None:
        return {}
    result: dict[str, sqlite3.Row] = {}
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


@dataclass
class NewCounterparty:
    """A counterparty of the e-qaimə the company does not have yet. The VÖEN identifies
    it; the portal's name is often long, so the user may give it another (`name`)."""

    tax_id: str
    portal_name: str
    name: str
    invoices: int = 1

    @property
    def key(self) -> str:
        return _party_key(self.tax_id, self.portal_name)


def _party_key(tax_id: str, name: str) -> str:
    return tax_id or f"name:{fold(name)}"  # a non-resident without VÖEN: by its name


# legal forms written out in full on the portal and their usual short forms
_LEGAL_FORMS = (
    ("MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ", "MMC"),
    ("AÇIQ SƏHMDAR CƏMİYYƏTİ", "ASC"),
    ("QAPALI SƏHMDAR CƏMİYYƏTİ", "QSC"),
    ("SƏHMDAR CƏMİYYƏTİ", "SC"),
    ("PUBLİK HÜQUQİ ŞƏXS", "PHŞ"),
    ("FƏRDİ SAHİBKAR", "FS"),
)


def short_name(name: str) -> str:
    """A suggestion for the program's name: the legal form shortened and put last, quotes
    and extra spaces dropped ('"ALFA TREYD" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ' -> 'ALFA TREYD
    MMC'). The user corrects it as they like."""
    text = " ".join(name.split())
    form = ""
    for full, short in _LEGAL_FORMS:
        position = fold(text).find(fold(full))
        if position >= 0:
            text = (text[:position] + text[position + len(full) :]).strip(" ,")
            form = short
            break
    for quote in "\"“”„«»'":
        text = text.replace(quote, "")
    text = " ".join(text.split())
    return f"{text} {form}".strip() if text else name.strip()


def new_counterparties(plans: Sequence[InvoicePlan]) -> list[NewCounterparty]:
    """The counterparties to add, one per VÖEN, with a shorter name suggested."""
    found: dict[str, NewCounterparty] = {}
    for plan in plans:
        invoice = plan.invoice
        if plan.counterparty_id is not None or not (invoice.party_tin or invoice.party_name):
            continue
        if plan.existing is not None:  # imported already: nothing new to add for it
            continue
        key = _party_key(invoice.party_tin, invoice.party_name)
        if key in found:
            found[key].invoices += 1
        else:
            found[key] = NewCounterparty(
                invoice.party_tin, invoice.party_name, short_name(invoice.party_name)
            )
    return sorted(found.values(), key=lambda c: fold(c.name))


def add_counterparties(
    ledger: Ledger,
    company_id: int,
    parties: Sequence[NewCounterparty],
    plans: Sequence[InvoicePlan] = (),
) -> dict[str, int]:
    """Add the counterparties with their VÖEN (one that has appeared meanwhile is taken as
    it is) and point the plans at them: key -> id."""
    ids: dict[str, int] = {}
    with transaction(ledger.conn):
        kind = ledger.subconto_kind_id(company_id, "counterparty")
        for party in parties:
            existing = _counterparty(ledger.conn, company_id, party.tax_id, party.portal_name)
            if existing is not None:
                ids[party.key] = existing
                continue
            name = " ".join(party.name.split()) or party.portal_name or party.tax_id
            value_id = ledger.add_subconto_value(company_id, kind, name or tr("Без названия"))
            if party.tax_id:
                ledger.set_subconto_value_tax(company_id, value_id, party.tax_id)
            if party.portal_name:
                ledger.set_subconto_value_legal_name(company_id, value_id, party.portal_name)
            ids[party.key] = value_id
        for plan in plans:
            if plan.counterparty_id is None:
                key = _party_key(plan.invoice.party_tin, plan.invoice.party_name)
                plan.counterparty_id = ids.get(key)
    return ids


def _same_name(a: str, b: str) -> bool:
    """Names equal but for case, quotes and spaces (the portal is not consistent in them)."""

    def plain(text: str) -> str:
        for quote in "\"“”„«»'":
            text = text.replace(quote, " ")
        return fold(" ".join(text.split()))

    return plain(a) == plain(b)


@dataclass
class RenamedCounterparty:
    """A counterparty whose official name on the portal is not the one remembered: the
    same VÖEN, a new name. `name` is what it will be called here if `rename`."""

    value_id: int
    tax_id: str
    old_legal_name: str
    new_legal_name: str
    current_name: str
    name: str
    rename: bool = True


def renamed_counterparties(
    conn: sqlite3.Connection, company_id: int, plans: Sequence[InvoicePlan]
) -> list[RenamedCounterparty]:
    """Known counterparties (by VÖEN) whose e-qaimə name differs from their remembered
    official name; the latest e-qaimə of the period gives the new name. One that has no
    official name yet is not asked about: it is remembered when imported."""
    latest: dict[int, EInvoice] = {}
    for plan in plans:
        invoice = plan.invoice
        if plan.counterparty_id is None or not invoice.party_tin or not invoice.party_name:
            continue
        seen = latest.get(plan.counterparty_id)
        if seen is None or invoice.doc_date >= seen.doc_date:
            latest[plan.counterparty_id] = invoice
    result = []
    for value_id, invoice in latest.items():
        row = conn.execute(
            "SELECT name, legal_name FROM subconto_values WHERE company_id = ? AND id = ?",
            (company_id, value_id),
        ).fetchone()
        if row is None or not row["legal_name"]:
            continue
        if _same_name(row["legal_name"], invoice.party_name):
            continue
        result.append(
            RenamedCounterparty(
                value_id,
                invoice.party_tin,
                row["legal_name"],
                invoice.party_name,
                row["name"],
                short_name(invoice.party_name),
            )
        )
    return sorted(result, key=lambda r: fold(r.current_name))


def apply_renames(ledger: Ledger, company_id: int, renames: Sequence[RenamedCounterparty]) -> None:
    """Remember the new official names; rename here those the user chose to (the history
    follows: postings refer to the counterparty, not its name)."""
    with transaction(ledger.conn):
        for item in renames:
            ledger.set_subconto_value_legal_name(company_id, item.value_id, item.new_legal_name)
            name = " ".join(item.name.split())
            if item.rename and name and name != item.current_name:
                code = ledger.conn.execute(
                    "SELECT code FROM subconto_values WHERE id = ?", (item.value_id,)
                ).fetchone()["code"]
                ledger.update_subconto_value(company_id, item.value_id, name, code)


def remember_legal_names(ledger: Ledger, company_id: int, plans: Sequence[InvoicePlan]) -> None:
    """Known counterparties without an official name get the one of their e-qaimə."""
    for plan in plans:
        if plan.counterparty_id is None or not plan.invoice.party_name:
            continue
        row = ledger.conn.execute(
            "SELECT legal_name FROM subconto_values WHERE company_id = ? AND id = ?",
            (company_id, plan.counterparty_id),
        ).fetchone()
        if row is not None and not row["legal_name"]:
            ledger.set_subconto_value_legal_name(
                company_id, plan.counterparty_id, plan.invoice.party_name
            )


def import_drafts(
    inventory: Inventory,
    company_id: int,
    plans: Sequence[InvoicePlan],
    names: Mapping[str, str] | None = None,
) -> list[int]:
    """Write the importable plans as drafts in one transaction. Missing counterparties are
    added first, once per VÖEN, under `names` (key -> name) or a shortened portal name;
    the settlement account is the one of its type (60 / 62)."""
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
            assert plan.counterparty_id is not None  # added above
            account = _settlement_account(conn, company_id, invoice.outgoing)
            subconto = _place(conn, account, kind, plan.counterparty_id)
            vat_rate = STANDARD_VAT_RATE if invoice.vat else None
            if invoice.outgoing:
                created.append(
                    inventory.create_sale_draft(
                        company_id,
                        invoice.doc_date,
                        [_sale_line(conn, p, warehouse) for p in plan.lines],
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
                        [_receipt_line(conn, p, warehouse) for p in plan.lines],
                        account,
                        subconto,
                        tr("Покупка по e-qaimə {n}", n=invoice.number),
                        vat_rate=vat_rate,
                        invoice=invoice.number,
                    )
                )
    return created


def _receipt_line(conn: sqlite3.Connection, plan: LinePlan, warehouse: int | None) -> ReceiptLine:
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
    )


def _sale_line(conn: sqlite3.Connection, plan: LinePlan, warehouse: int | None) -> SaleLine:
    line = plan.line
    goods = plan.item_id is not None
    return SaleLine(
        plan.item_id,
        warehouse if goods else None,
        _quantity(conn, plan.item_id, line.quantity),
        _amount(line.amount),
        _amount(line.vat, zero=True),
        line.name,
    )


def _amount(minor: int, zero: bool = False) -> Decimal | None:
    if minor == 0 and not zero:
        return None  # a draft may lack it; posting asks for it
    return Decimal(minor).scaleb(-2)


def _quantity(
    conn: sqlite3.Connection, item_id: int | None, quantity: Decimal | None
) -> Decimal | None:
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


def _only_warehouse(conn: sqlite3.Connection, company_id: int) -> int | None:
    rows = conn.execute(
        "SELECT w.id FROM warehouses w JOIN subconto_values v ON v.id = w.subconto_value_id "
        "WHERE w.company_id = ? AND v.active = 1 LIMIT 2",
        (company_id,),
    ).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def _settlement_account(conn: sqlite3.Connection, company_id: int, outgoing: bool) -> int | None:
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
    conn: sqlite3.Connection, account_id: int | None, kind_id: int, value_id: int
) -> tuple[int | None, int | None, int | None]:
    """The counterparty at its kind's position of the account (the contract stays empty)."""
    if account_id is None:
        return (None, None, None)
    account = conn.execute(
        "SELECT sc1_kind_id, sc2_kind_id, sc3_kind_id FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    return pad_subconto([value_id if k == kind_id else None for k in tuple(account)])
