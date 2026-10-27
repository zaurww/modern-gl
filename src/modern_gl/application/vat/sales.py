"""The facts of a sale's ƏDV: the money received from buyers by day — the value (to a bank
account or the cash desk) apart from the ƏDV (to the deposit account) — by the number of
the e-qaimə it names, or, with no number, as an advance of the buyer; and each e-qaimə's
day, amount and ƏDV (`book_invoices`, D120). Read from the posted documents of the common
book: a receipt is money debited against the buyer's settlement (62) or advance (62.2)
account, a refund the other way. An advance set against an e-qaimə moves no money and is
no receipt. The money paid to suppliers is read the same way, the other way round
(`party_money`, the reconciliation of payments with e-qaimə)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.book_invoices import book_invoices
from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import InvoiceAccount, invoice_accounts
from modern_gl.application.vat.facts import Payment
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection

_DOCS = docs_cte("d.id, d.doc_date")
BUYER_TYPES = frozenset({"receivable", ADVANCE_RECEIVED})
SUPPLIER_TYPES = frozenset({"payable", ADVANCE_PAID})


@dataclass
class SaleFacts:
    counterparty_id: int | None
    invoice: str | None  # None: money received without a number — an advance
    doc_date: str = ""  # the e-qaimə's day; "" — none yet
    amount: int = 0  # the e-qaimə's value without ƏDV
    vat: int = 0  # its ƏDV
    receipts: list[Payment] = field(default_factory=list)  # by day, in order

    def receive(self, day: str, main: int = 0, vat: int = 0) -> None:
        if self.receipts and self.receipts[-1].day == day:
            self.receipts[-1].main += main
            self.receipts[-1].vat += vat
        else:
            self.receipts.append(Payment(day, main, vat))


def sale_facts(
    conn: Connection, company_id: int, date_to: date | str, layers=COMMON
) -> list[SaleFacts]:
    """The money received from buyers up to `date_to`, by e-qaimə number (an advance — by
    buyer), with the e-qaimə it names."""
    found = party_money(conn, company_id, date_to, outgoing=True, layers=layers)
    sales = book_invoices(conn, company_id, outgoing=True, layers=layers)
    for facts in found:
        sale = sales.get(facts.invoice) if facts.invoice is not None else None
        if sale is not None and sale.doc_date <= iso_date(date_to):
            facts.doc_date, facts.amount, facts.vat = sale.doc_date, sale.amount, sale.vat
    return found


def party_money(
    conn: Connection, company_id: int, date_to: date | str, outgoing: bool, layers=COMMON
) -> list[SaleFacts]:
    """The money from buyers (`outgoing`) or to suppliers up to `date_to`, by e-qaimə
    number, or without one by counterparty; `main` — to or from a bank account or the
    cash desk, `vat` — the ƏDV deposit (or from a bank account to the supplier's deposit,
    `pays_vat`). A refund is negative."""
    params = book_params(conn, company_id, date_to, date_to, layers)
    accounts = invoice_accounts(conn, company_id)
    types = BUYER_TYPES if outgoing else SUPPLIER_TYPES
    parties = [i for i, a in accounts.items() if a.account_type in types]
    if not parties:
        return []
    money = [i for i, a in accounts.items() if a.money]
    if not money:
        return []
    found: dict[tuple, SaleFacts] = {}
    # only money against the counterparty's account, no customs declaration (`_count`)
    marks = ", ".join(str(i) for i in parties)
    cash = ", ".join(str(i) for i in money)
    for p in conn.execute(
        f"""
        WITH {_DOCS}
        SELECT p.invoice, COALESCE(p.invoice_kind, '') AS kind, docs.doc_date, p.amount,
               p.debit_account_id, p.credit_account_id, p.pays_vat,
               p.dt_sc1, p.dt_sc2, p.dt_sc3, p.ct_sc1, p.ct_sc2, p.ct_sc3
        FROM postings p JOIN docs ON docs.id = p.document_id
        WHERE p.company_id = :company_id
          AND COALESCE(p.invoice_kind, '') = ''
          AND ((p.debit_account_id IN ({cash}) AND p.credit_account_id IN ({marks}))
               OR (p.credit_account_id IN ({cash}) AND p.debit_account_id IN ({marks})))
        ORDER BY docs.doc_date, p.document_id, p.line_no
        """,
        params,
    ):
        _count(found, p, accounts, types, 1 if outgoing else -1)
    return list(found.values())


def _count(
    found: dict[tuple, SaleFacts],
    p,
    accounts: dict[int, InvoiceAccount],
    types: frozenset[str],
    way: int,
) -> None:
    """Money against the counterparty's account: received from a buyer (`way` 1) or paid
    to a supplier (-1); the other way — a refund."""
    debit, credit = accounts[p["debit_account_id"]], accounts[p["credit_account_id"]]
    if debit.money and credit.account_type in types:
        money, buyer, prefix, sign = debit, credit, "ct", way
    elif credit.money and debit.account_type in types:
        money, buyer, prefix, sign = credit, debit, "dt", -way
    else:
        return  # the e-qaimə itself, an offset of an advance, anything else
    if p["kind"]:  # a customs declaration is no sale
        return
    who = p[f"{prefix}_sc{buyer.partner_at}"] if buyer.partner_at else None
    number = p["invoice"]
    key = (who if number is None else None, number)
    facts = found.setdefault(key, SaleFacts(who, number))
    if facts.counterparty_id is None:
        facts.counterparty_id = who
    if money.account_type == "vat_deposit" or p["pays_vat"]:  # to a supplier's deposit
        facts.receive(p["doc_date"], vat=sign * p["amount"])
    else:
        facts.receive(p["doc_date"], main=sign * p["amount"])
