"""What a counterparty paid without a number, set against the unpaid list: a payment made
before its e-qaimə was known pays it, whatever was entered first — the order of entry
changes nothing (D206). A calculation, oldest first as the ƏDV module
lays the same money out (D185); no posting changes and a number stays what it was.

The free money is the counterparty's balance without a number on its settlement and
advance accounts: an unnumbered debt (an act) takes its money first. `open_invoices` keeps
the balance by number — what an advance offset and a number in a purpose read."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date

from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import invoice_accounts
from modern_gl.application.invoices import (
    UNPAID,
    InvoiceRow,
    OpenInvoice,
    gathered_invoices,
    open_invoices,
    same_firm,
)
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


# Dt − Kt without a number on the accounts of a side, by account and subconto: every
# counterparty at once, for a report
_BY_ACCOUNT_SQL = f"""
WITH {docs_cte()},
sides AS (SELECT value AS id FROM json_each(:sides)),
moved AS (
    SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc1, p.dt_sc2 AS sc2, p.dt_sc3 AS sc3,
           p.amount AS money
    FROM postings p JOIN docs ON docs.id = p.document_id
    WHERE p.company_id = :company_id AND p.invoice IS NULL
      AND p.debit_account_id IN (SELECT id FROM sides)
    UNION ALL
    SELECT p.credit_account_id AS account_id, p.ct_sc1 AS sc1, p.ct_sc2 AS sc2, p.ct_sc3 AS sc3,
           -p.amount AS money
    FROM postings p JOIN docs ON docs.id = p.document_id
    WHERE p.company_id = :company_id AND p.invoice IS NULL
      AND p.credit_account_id IN (SELECT id FROM sides)
)
SELECT account_id, sc1, sc2, sc3, SUM(money) AS money FROM moved
GROUP BY account_id, sc1, sc2, sc3"""


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


def _firms(conn: Connection, company_id: int) -> dict[int, int]:
    """Counterparty -> the first element with its VÖEN: one firm, however many elements."""
    first: dict[str, int] = {}
    found: dict[int, int] = {}
    for r in conn.execute(
        "SELECT v.id, v.tax_id FROM subconto_values v "
        "JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'counterparty' "
        "WHERE v.company_id = ? AND v.tax_id IS NOT NULL ORDER BY v.id",
        (company_id,),
    ):
        found[r["id"]] = first.setdefault(r["tax_id"], r["id"])
    return found


def _free_by_firm(
    conn: Connection, company_id: int, payable: bool, params: dict, firms: dict[int, int]
) -> dict[int, int]:
    """What `free_money` gives, for every counterparty in one query, by firm."""
    accounts = invoice_accounts(conn, company_id)
    sides = [i for i, a in accounts.items() if a.account_type in _SIDES[payable]]
    if not sides:
        return {}
    found: dict[int, int] = {}
    way = 1 if payable else -1
    for r in conn.execute(_BY_ACCOUNT_SQL, {**params, "sides": json.dumps(sides)}):
        at = accounts[r["account_id"]].partner_at
        who: int | None = r[f"sc{at}"] if at else None
        if who is not None:
            firm = firms.get(who) or who
            found[firm] = found.get(firm, 0) + way * r["money"]
    return found


def mark_free_money(
    conn: Connection,
    company_id: int,
    rows: Iterable[InvoiceRow],
    on_date: date | str,
    layers: Sequence[str] = COMMON,
) -> None:
    """Each e-qaimə of `rows` gets what the money without a number paid of it (`free`):
    over every unpaid one of the day, oldest first, whichever of them `rows` shows."""
    params = book_params(conn, company_id, on_date, on_date, layers)
    unpaid = [
        r
        for (kind, _), r in gathered_invoices(conn, company_id, params, only=UNPAID).items()
        if kind == ""
    ]
    if not unpaid:
        return
    firms = _firms(conn, company_id)
    free = {way: _free_by_firm(conn, company_id, way, params, firms) for way in (True, False)}
    taken: dict[str, int] = {}
    for row in sorted(unpaid, key=lambda r: (r.doc_date, r.invoice)):
        who = row.counterparty_id
        if who is None:
            continue
        left = free[row.balance < 0]
        firm = firms.get(who, who)
        take = min(max(left.get(firm, 0), 0), abs(row.balance))
        if take:
            left[firm] -= take
            taken[row.invoice] = take
    for row in rows:
        if row.kind == "":
            row.free = taken.get(row.invoice, 0)


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
