"""Counterparties of the e-qaimə: new ones by VÖEN with a short name, renamed ones,
the legal names remembered."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.application.counterparties import known_counterparty, short_name
from modern_gl.application.eqaime_import.parsing import EInvoice
from modern_gl.application.eqaime_import.planning import InvoicePlan
from modern_gl.application.ledger import Ledger
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection, transaction


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
            existing = known_counterparty(ledger.conn, company_id, party.tax_id, party.portal_name)
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
    conn: Connection, company_id: int, plans: Sequence[InvoicePlan]
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
