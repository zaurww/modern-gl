"""What a counterparty paid without a number, set against the unpaid list: a payment made
before its e-qaimə was known pays it, whatever was entered first — the order of entry
changes nothing (D206). A calculation, oldest first as the ƏDV module
lays the same money out (D185); no posting changes and a number stays what it was.

The free money is the counterparty's balance without a number on its settlement and
advance accounts: an unnumbered debt (an act) takes its money first. `open_invoices` keeps
the balance by number — what an advance offset and a number in a purpose read."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import invoice_accounts
from modern_gl.application.invoices import OpenInvoice, open_invoices, same_firm
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.infrastructure.db import Connection

_SIDES = {True: ("payable", ADVANCE_PAID), False: ("receivable", ADVANCE_RECEIVED)}
# Dt − Kt without a number on the accounts of the side, of the counterparty; `vat` — the
# part of it to or from a deposit
_FREE_SQL = f"""
WITH {docs_cte()},
sides AS (SELECT value AS id FROM json_each(:sides)),
who AS (SELECT value AS id FROM json_each(:who)),
deposits AS (SELECT value AS id FROM json_each(:deposits)),
moved AS (
    SELECT p.amount AS money,
           CASE WHEN p.pays_vat = 1 OR p.credit_account_id IN (SELECT id FROM deposits)
                THEN p.amount ELSE 0 END AS vat
    FROM postings p JOIN docs ON docs.id = p.document_id
    WHERE p.company_id = :company_id AND p.invoice IS NULL AND p.document_id <> :without
      AND p.debit_account_id IN (SELECT id FROM sides)
      AND (p.dt_sc1 IN (SELECT id FROM who) OR p.dt_sc2 IN (SELECT id FROM who)
           OR p.dt_sc3 IN (SELECT id FROM who))
    UNION ALL
    SELECT -p.amount AS money,
           CASE WHEN p.pays_vat = 1 OR p.debit_account_id IN (SELECT id FROM deposits)
                THEN -p.amount ELSE 0 END AS vat
    FROM postings p JOIN docs ON docs.id = p.document_id
    WHERE p.company_id = :company_id AND p.invoice IS NULL AND p.document_id <> :without
      AND p.credit_account_id IN (SELECT id FROM sides)
      AND (p.ct_sc1 IN (SELECT id FROM who) OR p.ct_sc2 IN (SELECT id FROM who)
           OR p.ct_sc3 IN (SELECT id FROM who))
)
SELECT COALESCE(SUM(money), 0) AS money, COALESCE(SUM(vat), 0) AS vat FROM moved"""


def free_money(
    conn: Connection,
    company_id: int,
    counterparty_id: int,
    payable: bool,
    on_date: date | str,
    layers: Sequence[str] = COMMON,
    without: int | None = None,
) -> tuple[int, int]:
    """(the money paid without a number and not owed back on anything without one, of it
    the ƏDV: to a deposit) at the end of the day; `without` — a document left out."""
    accounts = invoice_accounts(conn, company_id)
    sides = [i for i, a in accounts.items() if a.account_type in _SIDES[payable]]
    if not sides:
        return 0, 0
    parties, _ = same_firm(conn, company_id, counterparty_id)
    deposits = [i for i, a in accounts.items() if a.account_type == "vat_deposit"]
    row = conn.execute(
        _FREE_SQL,
        {
            **book_params(conn, company_id, on_date, on_date, layers),
            "sides": json.dumps(sides),
            "who": json.dumps(sorted(parties)),
            "deposits": json.dumps(deposits),
            "without": without or 0,
        },
    ).fetchone()
    way = 1 if payable else -1  # the sums are Dt − Kt: paid to a supplier, owed by a customer
    return max(way * row["money"], 0), max(way * row["vat"], 0)


def lay_out(invoices: Sequence[OpenInvoice], money: int, vat: int) -> list[OpenInvoice]:
    """The list with the money taken off, oldest first; the ƏDV's money off their ƏDV.
    What is paid in full leaves the list."""
    found = []
    for invoice in invoices:
        take = min(invoice.amount, money)
        money -= take
        take_vat = min(invoice.vat, vat)
        vat -= take_vat
        left = invoice.amount - take
        if left > 0:
            found.append(replace(invoice, amount=left, vat=min(invoice.vat - take_vat, left)))
    return found


def unpaid_invoices(
    conn: Connection,
    company_id: int,
    counterparty_id: int,
    payable: bool,
    on_date: date | str,
    layers: Sequence[str] = COMMON,
    without: int | None = None,
) -> list[OpenInvoice]:
    """What is really unpaid on the day: `open_invoices` less the money without a number.
    `without` — the document being edited: a payment does not pay what it is to name."""
    found = open_invoices(conn, company_id, counterparty_id, payable, on_date, layers)
    money = free_money(conn, company_id, counterparty_id, payable, on_date, layers, without)
    return lay_out(found, *money)
