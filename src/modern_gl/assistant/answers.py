"""What the assistant's tools answer: the reports and the books as plain JSON (D83).

Amounts are strings in manat with two decimals ("1234.50") — exact, never floats; a
debit/credit pair is written once as {"debit", "credit"}. Long lists are cut at LIMIT and
say how many were left out, so the model asks for a narrower period instead of guessing.
"""

from __future__ import annotations

from modern_gl.application import queries
from modern_gl.application.catalog import Catalog
from modern_gl.domain.accounts import is_current
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import invoices as invoice_reports
from modern_gl.reporting import reports
from modern_gl.reporting.report_common import BOOKS, Turnovers

LIMIT = 500


def money(minor: int) -> str:
    return format_minor(minor).replace(" ", "")


def _pair(debit: int, credit: int) -> dict:
    return {"debit": money(debit), "credit": money(credit)}


def _turnovers(t: Turnovers) -> dict:
    return {
        "opening": _pair(t.opening_dt, t.opening_ct),
        "turnover": _pair(t.turnover_dt, t.turnover_ct),
        "closing": _pair(t.closing_dt, t.closing_ct),
    }


def _layers(book: str) -> tuple[str, ...]:
    if book not in BOOKS:
        raise ValueError(tr("книга: {books}", books=", ".join(BOOKS)))
    return BOOKS[book]


def _cut(items: list, limit: int = LIMIT) -> tuple[list, int]:
    return items[:limit], max(len(items) - limit, 0)


TERMS = {True: "current", False: "long_term", None: ""}  # domain.accounts.is_current


def chart_of_accounts(conn: Connection, company_id: int) -> dict:
    cat = Catalog(conn, company_id)
    accounts = []
    for a in cat.accounts.values():
        parent = cat.accounts.get(a.parent_id) if a.parent_id else None
        accounts.append(
            {
                "code": a.code,
                "name": a.name,
                "group": a.is_group,
                "parent": parent.short if parent else "",
                "class": a.account_class or "",
                "type": a.account_type or "",
                "term": TERMS[is_current(a.account_type)],
                "contra": a.contra,
                "two_sided": a.two_sided,
                "currency_mode": a.currency,
                "subconto": [cat.kinds[k] for k in a.sc_kinds if k is not None],
                "hidden": not a.active,
            }
        )
    return {"accounts": accounts, "directories": sorted(cat.kinds.values())}


def trial_balance(
    conn: Connection, company_id: int, date_from: str, date_to: str, book: str = "common"
) -> dict:
    osv = reports.trial_balance(conn, company_id, date_from, date_to, _layers(book))
    rows = [
        {
            "code": r.code,
            "name": r.name,
            "depth": r.depth,
            "group": r.is_group,
            **_turnovers(r),
            "wrong_side": r.opening_wrong or r.closing_wrong,
        }
        for r in osv.rows
        if not r.is_zero()
    ]
    return {
        "period": [date_from, date_to],
        "book": book,
        "rows": rows,
        "total": _turnovers(osv.total),
        "wrong_side": [r.code or r.name for r in osv.wrong_side],
    }


def account_card(
    conn: Connection,
    company_id: int,
    account: str,
    date_from: str,
    date_to: str,
    book: str = "common",
) -> dict:
    card = reports.account_card(conn, company_id, account, date_from, date_to, _layers(book))
    lines, left_out = _cut(card.lines)
    return {
        "account": account,
        "period": [date_from, date_to],
        "opening_balance": money(card.opening),
        "lines": [
            {
                "date": c.doc_date,
                "document": c.number,
                "memo": c.memo,
                "corr_account": c.corr_code,
                **_pair(c.debit, c.credit),
                "balance": money(c.balance),
                **(
                    {
                        "currency": c.currency,
                        "in_currency": _pair(c.currency_debit, c.currency_credit),
                    }
                    if c.currency
                    else {}
                ),
                **({"e_qaime": c.invoice} if c.invoice else {}),
            }
            for c in lines
        ],
        "left_out": left_out,
        "closing_balance": money(card.closing),
        "balance_note": "balance = debit - credit",
    }


def account_analysis(
    conn: Connection,
    company_id: int,
    account: str,
    date_from: str,
    date_to: str,
    book: str = "common",
) -> dict:
    rows = reports.account_analysis(conn, company_id, account, date_from, date_to, _layers(book))
    return {
        "account": account,
        "period": [date_from, date_to],
        "by_corr_account": [
            {"code": r.corr_code, "name": r.corr_name, **_pair(r.debit, r.credit)} for r in rows
        ],
    }


def subconto_balance(
    conn: Connection,
    company_id: int,
    account: str,
    date_from: str,
    date_to: str,
    position: int = 1,
    book: str = "common",
) -> dict:
    rows = reports.subconto_balance(
        conn, company_id, account, date_from, date_to, _layers(book), position
    )
    shown, left_out = _cut(rows)
    return {
        "account": account,
        "period": [date_from, date_to],
        "rows": [
            {
                "name": r.name or tr("<не указано>"),
                **_turnovers(r),
                **(
                    {"currency_closing": {k: money(v) for k, v in r.currency_closing.items()}}
                    if r.currency_closing
                    else {}
                ),
            }
            for r in shown
        ],
        "left_out": left_out,
    }


def documents(
    conn: Connection,
    company_id: int,
    date_from: str,
    date_to: str,
    search: str = "",
    drafts_only: bool = False,
) -> dict:
    found = queries.list_documents(conn, company_id, date_from, date_to)
    if drafts_only:
        found = [d for d in found if d.status == "draft"]
    if search.strip():
        wanted = fold(search.strip())
        found = [d for d in found if wanted in fold(d.memo) or wanted == str(d.number)]
    shown, left_out = _cut(found)
    return {
        "documents": [
            {
                "number": d.number,
                "date": d.doc_date,
                "memo": d.memo,
                "status": d.status_text,
                "draft": d.status == "draft",
                "book_layer": d.layer,
                "total": money(d.total),
                "lines": d.lines,
            }
            for d in shown
        ],
        "left_out": left_out,
    }


def document(conn: Connection, company_id: int, number: int) -> dict:
    doc = queries.load_document(
        conn, company_id, queries.document_by_number(conn, company_id, number)
    )
    cat = Catalog(conn, company_id)

    def side(account_id: int, subconto: tuple[int | None, ...]) -> dict:
        return {
            "account": cat.accounts[account_id].label,
            "subconto": [cat.value(v).name for v in subconto if v is not None],
        }

    made_by = (
        "warehouse/trade document"
        if doc.inventory_document_id
        else "currency conversion"
        if doc.conversion_id
        else "bank operation"
        if doc.bank_operation_id
        else ""
    )
    return {
        "number": doc.number,
        "date": doc.doc_date,
        "memo": doc.memo,
        "status": doc.status,
        "book_layer": doc.layer,
        "made_by_module": made_by,
        "postings": [
            {
                "debit": side(p.debit_account_id, p.debit_subconto),
                "credit": side(p.credit_account_id, p.credit_subconto),
                "amount": money(p.amount),
                "memo": p.memo,
                **(
                    {
                        "currency": cat.currencies[p.currency_id].code,
                        "currency_amount": money(p.currency_amount or 0),
                    }
                    if p.currency_id
                    else {}
                ),
                **({"e_qaime": p.invoice} if p.invoice else {}),
            }
            for p in doc.postings
        ],
    }


def directory(conn: Connection, company_id: int, name: str, search: str = "") -> dict:
    cat = Catalog(conn, company_id)
    wanted = fold(name.strip())
    kinds = [k for k, n in cat.kinds.items() if wanted in (fold(n), fold(cat.kind_codes[k]))]
    if len(kinds) != 1:
        raise ValueError(tr("справочник: {names}", names=", ".join(sorted(cat.kinds.values()))))
    values = cat.all_values(kinds[0])
    if search.strip():
        text = fold(search.strip())
        values = [v for v in values if text in fold(v.name) or text in (v.tax_id or "")]
    shown, left_out = _cut(values)
    return {
        "directory": cat.kinds[kinds[0]],
        "elements": [
            {
                "name": v.name,
                **({"voen": v.tax_id} if v.tax_id else {}),
                **({"nonresident": True, "country": v.country or ""} if v.nonresident else {}),
                **({"group": cat.group_path(v.id)} if v.parent_id else {}),
                **({"is_group": True} if v.is_group else {}),
                **({"owner": cat.value(v.owner_id).name} if v.owner_id else {}),
                **({"tags": [cat.tags[t] for t in sorted(v.tags)]} if v.tags else {}),
                **({"hidden": True} if not v.active else {}),
            }
            for v in shown
        ],
        "left_out": left_out,
    }


def e_qaime(
    conn: Connection, company_id: int, date_from: str, date_to: str, unpaid_only: bool = False
) -> dict:
    rows = invoice_reports.invoice_report(
        conn, company_id, date_from, date_to, open_only=unpaid_only
    )
    cat = Catalog(conn, company_id)
    shown, left_out = _cut(rows)
    return {
        "period": [date_from, date_to],
        "e_qaime": [
            {
                "number": r.invoice,
                "date": r.doc_date,
                "customs_declaration": r.kind == "customs",
                "counterparty": [cat.value(c).name for c in r.counterparties],
                **_pair(r.debit, r.credit),
                "vat": money(r.vat),
                "unpaid_balance": money(r.balance),
                "documents": [n for _, n in r.documents],
            }
            for r in shown
        ],
        "left_out": left_out,
        "balance_note": "settlement accounts debit - credit: > 0 a sale unpaid, < 0 we owe",
    }
