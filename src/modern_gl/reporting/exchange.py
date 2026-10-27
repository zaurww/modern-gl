"""Posted documents as an exchange file (D130, docs/EXCHANGE.md): the format
`application/exchange` reads, so a period goes to another program, or into another
company, and back. A document is named by its number; the file's source is the company.
Accounts by code (an account without one — by name: such a line will not import back),
directory elements by name."""

from __future__ import annotations

from datetime import date
from typing import Any

from modern_gl.application.books import BOOKS, book_params
from modern_gl.application.exchange import FORMAT, VERSION
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.plaintext import posted_documents
from modern_gl.reporting.report_common import _accounts

SOURCE = "modern-gl/"  # + the company's name


def documents_file(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    book: str = "common",
) -> dict[str, Any]:
    """The posted documents of the period in the book, ready for `json.dump`."""
    params = book_params(conn, company_id, date_from, date_to, BOOKS[book])
    accounts = {a: r["code"] or r["name"] for a, r in _accounts(conn, company_id).items()}
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
        )
    }
    company = conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()
    return {
        "format": FORMAT,
        "version": VERSION,
        "source": SOURCE + company["name"],
        "documents": [
            {
                "id": str(doc["number"]),
                "date": doc["doc_date"],
                "memo": doc["memo"],
                "layer": doc["layer"],
                **(
                    {"reverses": str(doc["reversal_of"])}
                    if doc["reversal_of"] is not None
                    else {"postings": [_line(p, accounts, names) for p in postings]}
                ),
            }
            for doc, postings in posted_documents(conn, params)
        ],
    }


def _line(p: Row, accounts: dict[int, str], names: dict[int, str]) -> dict:
    line: dict = {
        "debit": accounts[p["debit_account_id"]],
        "credit": accounts[p["credit_account_id"]],
        "amount": _money(p["amount"]),
    }
    for side, key in (("dt", "debit_subconto"), ("ct", "credit_subconto")):
        values = [p[f"{side}_sc{i}"] for i in (1, 2, 3)]
        while values and values[-1] is None:
            values.pop()
        if values:
            line[key] = [names[v] if v is not None else "" for v in values]
    if p["currency_code"]:
        line["currency"] = p["currency_code"]
        line["currency_amount"] = _money(p["currency_amount"])
    if p["invoice"]:
        line["customs" if p["invoice_kind"] == "customs" else "e_qaime"] = p["invoice"]
    if p["pays_vat"]:
        line["pays_vat"] = True
    if p["line_memo"]:
        line["memo"] = p["line_memo"]
    return line


def _money(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 100)
    return f"{sign}{whole}.{frac:02d}"
