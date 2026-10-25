"""The facts of a purchase's ƏDV by the number of its e-qaimə or customs declaration: the
document's date, its amount and ƏDV, what was paid when — the amount and the ƏDV apart.
Read from the posted documents of the common book; what a posting counts as follows the
rule of the invoice number (`invoice_rules`, D120)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import (
    InvoiceAccount,
    invoice_accounts,
    is_accrual,
    is_vat_accrual,
    turnover_sides,
)
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.infrastructure.db import Connection

_DOCS = docs_cte("d.id, d.doc_date")


@dataclass
class Payment:
    """What was paid on the number on a day: the amount (from a bank account, or an
    advance set against the e-qaimə) and the ƏDV (to the deposit account, or to the customs)."""

    day: str
    main: int = 0
    vat: int = 0


@dataclass
class InvoiceFacts:
    kind: str  # domain.invoice: "" an e-qaimə, CUSTOMS a declaration
    invoice: str
    doc_date: str = ""  # the first accrual's day
    document_id: int | None = None  # the first accrual's GL document
    counterparty_id: int | None = None
    amount: int = 0  # accrued without ƏDV
    vat: int = 0  # accrued ƏDV (the input VAT account's)
    payments: list[Payment] = field(default_factory=list)  # by day, in order
    # the settlement the ƏDV is owed on (the customs for a declaration)
    vat_settlement: tuple[int, tuple[int | None, ...]] | None = None

    def pay(self, day: str, main: int = 0, vat: int = 0) -> None:
        if self.payments and self.payments[-1].day == day:
            self.payments[-1].main += main
            self.payments[-1].vat += vat
        else:
            self.payments.append(Payment(day, main, vat))


def purchase_facts(
    conn: Connection, company_id: int, date_to: date | str, layers=COMMON
) -> list[InvoiceFacts]:
    """The purchases with ƏDV up to `date_to`, by number, earliest first: the ones whose
    ƏDV went to the input VAT account."""
    params = book_params(conn, company_id, date_to, date_to, layers)
    accounts = invoice_accounts(conn, company_id)
    found: dict[tuple[str, str], InvoiceFacts] = {}
    for p in conn.execute(
        f"""
        WITH {_DOCS}
        SELECT p.invoice, COALESCE(p.invoice_kind, '') AS kind, p.document_id, docs.doc_date,
               p.amount, p.debit_account_id, p.credit_account_id,
               p.dt_sc1, p.dt_sc2, p.dt_sc3, p.ct_sc1, p.ct_sc2, p.ct_sc3
        FROM postings p JOIN docs ON docs.id = p.document_id
        WHERE p.company_id = :company_id AND p.invoice IS NOT NULL
        ORDER BY docs.doc_date, p.document_id, p.line_no
        """,
        params,
    ):
        facts = found.setdefault((p["kind"], p["invoice"]), InvoiceFacts(p["kind"], p["invoice"]))
        _count(facts, p, accounts)
    return [f for f in found.values() if f.vat > 0 and f.vat_settlement is not None and f.doc_date]


def _count(facts: InvoiceFacts, p, accounts: dict[int, InvoiceAccount]) -> None:
    """What one posting of the number is to the purchase."""
    debit, credit = accounts[p["debit_account_id"]], accounts[p["credit_account_id"]]
    dt_sc = (p["dt_sc1"], p["dt_sc2"], p["dt_sc3"])
    ct_sc = (p["ct_sc1"], p["ct_sc2"], p["ct_sc3"])
    if is_vat_accrual(debit, credit) and debit.account_type == INPUT_VAT:
        facts.vat += p["amount"]
        facts.vat_settlement = (p["credit_account_id"], ct_sc)
        _first(facts, p, credit, ct_sc)
        return
    if is_vat_accrual(credit, debit) and credit.account_type == INPUT_VAT:
        facts.vat -= p["amount"]  # a correction of the ƏDV
        return
    dt_turn, ct_turn = turnover_sides(debit, credit)
    if ct_turn and is_accrual(credit, debit):  # Dt 41 / Kt 60: the e-qaimə itself
        facts.amount += p["amount"]
        _first(facts, p, credit, ct_sc)
    elif dt_turn and is_accrual(debit, credit):  # a return to the supplier
        facts.amount -= p["amount"]
    elif dt_turn:  # Dt 60 / Kt 51, Kt 54 or Kt 60.2: a payment, or an advance set against
        if _pays_vat(facts, credit, p["debit_account_id"], dt_sc):
            facts.pay(p["doc_date"], vat=p["amount"])
        else:
            facts.pay(p["doc_date"], main=p["amount"])
    elif ct_turn and debit.money:  # Dt 51 / Kt 60: money back from the supplier
        if _pays_vat(facts, debit, p["credit_account_id"], ct_sc):
            facts.pay(p["doc_date"], vat=-p["amount"])
        else:
            facts.pay(p["doc_date"], main=-p["amount"])


def _pays_vat(facts: InvoiceFacts, money: InvoiceAccount, settlement_id: int, sc: tuple) -> bool:
    """A payment of the ƏDV: from the deposit account (D41), or — on a customs
    declaration — to the customs, the settlement the ƏDV is owed on."""
    if money.account_type == "vat_deposit":
        return True
    return facts.kind == CUSTOMS and facts.vat_settlement == (settlement_id, sc)


def _first(facts: InvoiceFacts, p, settlement: InvoiceAccount, sc: tuple) -> None:
    """The first accrual names the day, the document and the counterparty."""
    if not facts.doc_date:
        facts.doc_date, facts.document_id = p["doc_date"], p["document_id"]
    if facts.counterparty_id is None and settlement.partner_at is not None:
        facts.counterparty_id = sc[settlement.partner_at - 1]
