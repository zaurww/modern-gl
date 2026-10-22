"""The company's postings as a plain-text double-entry journal (hledger format, D79).

Export only: the database stays the one source of truth, the journal is derived like any
report. One document = one transaction; each Dt/Ct posting gives two lines, so every
transaction balances. Amounts are in manat (as in the ОСВ); a currency side carries its
currency amount as a tag. Subconto become tags. Accounts are declared with their types,
so `hledger bs` / `hledger is` work out of the box.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import _DOCS_CTE, COMMON, _accounts, _params

BASE = "AZN"
_TYPES = {"asset": "A", "liability": "L", "equity": "E", "revenue": "R", "expense": "X"}
_EARLIEST = "0001-01-01"


def hledger_journal(
    conn: Connection,
    company_id: int,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    generated: date | str | None = None,
) -> str:
    """Posted documents of the book `layers` up to `date_to` as hledger journal text."""
    params = _params(conn, company_id, _EARLIEST, date_to, layers)
    accounts = _accounts(conn, company_id)
    names = {a: account_name(accounts, a) for a in accounts}
    values = _subconto_names(conn, company_id)
    out = _header(conn, company_id, params["date_to"], layers, generated)
    out += _declarations(accounts, names)
    for doc, postings in _documents(conn, params):
        out.append("")
        out.append(_transaction_line(doc))
        for p in postings:
            for side, column, sign in (("dt", "debit", 1), ("ct", "credit", -1)):
                account = accounts[p[f"{column}_account_id"]]
                line = _posting_line(names[account["id"]], sign * p["amount"])
                tags = _tags(p, side, values)
                if account["currency"] and p["currency_code"]:
                    money = f"{_amount(sign * p['currency_amount'])} {p['currency_code']}"
                    tags.append((tr("валюта"), money))
                if tags:
                    line += "  ; " + ", ".join(f"{k}: {v}" for k, v in tags)
                out.append(line)
    return "\n".join(out) + "\n"


def account_name(accounts: dict[int, Row], account_id: int) -> str:
    """Full hledger name: the path from the top group, «60 Поставщики:60.1 В манатах»."""
    parts = []
    current: int | None = account_id
    while current is not None:
        a = accounts[current]
        label = f"{a['code']} {a['name']}" if a["code"] else a["name"]
        parts.append(_clean(label, ":"))
        current = a["parent_id"]
    name = ":".join(reversed(parts))
    if name[0] in "([":  # «(account)» would be a virtual posting in hledger
        name = re.sub(r"[()\[\]]", "", name).strip()
    return name


def _clean(text: str, *extra: str) -> str:
    """One line, single spaces, no characters that end a field in the journal syntax."""
    for ch in (";", *extra):
        text = text.replace(ch, ",")
    return re.sub(r"\s+", " ", text).strip()


def _amount(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 100)
    return f"{sign}{whole}.{frac:02d}"


def _header(conn, company_id, date_to, layers, generated) -> list[str]:
    company = conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()
    book = ", ".join(
        r["name"]
        for r in conn.execute(
            "SELECT code, name FROM layers WHERE company_id = ? ORDER BY id", (company_id,)
        )
        if r["code"] in layers
    )
    lines = [
        f"; {_clean(company['name'])}",
        "; " + tr("Журнал проводок по {date} — книга: {book}", date=date_to, book=book),
    ]
    if generated is not None:
        lines.append("; " + tr("Выгружено {date} из Modern GL", date=iso_date(generated)))
    return [*lines, "", f"commodity 1000.00 {BASE}", ""]


def _declarations(accounts: dict[int, Row], names: dict[int, str]) -> list[str]:
    lines = []
    for a in sorted(accounts.values(), key=lambda a: names[a["id"]]):
        kind = _TYPES.get(a["account_class"] or "")
        lines.append(f"account {names[a['id']]}" + (f"  ; type: {kind}" if kind else ""))
    return lines


def _subconto_names(conn: Connection, company_id: int) -> dict[int, tuple[str, str]]:
    """Subconto value id -> (tag name from its kind, value name)."""
    rows = conn.execute(
        """
        SELECT v.id, k.name AS kind, v.name
        FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id
        WHERE v.company_id = ?
        """,
        (company_id,),
    )
    return {
        r["id"]: (_clean(r["kind"], ":", ",").replace(" ", "_"), _clean(r["name"], ","))
        for r in rows
    }


def _documents(conn: Connection, params: dict) -> list[tuple[Row, list[Row]]]:
    rows = conn.execute(
        f"""
        WITH {_DOCS_CTE}
        SELECT docs.id AS doc_id, docs.doc_date, docs.number, docs.memo,
               orig.number AS reversal_of, l.code AS layer, l.name AS layer_name,
               p.debit_account_id, p.credit_account_id, p.amount,
               p.dt_sc1, p.dt_sc2, p.dt_sc3, p.ct_sc1, p.ct_sc2, p.ct_sc3,
               p.currency_amount, c.code AS currency_code, p.invoice, p.invoice_kind,
               p.memo AS line_memo
        FROM docs
        JOIN documents d ON d.id = docs.id
        JOIN layers l ON l.id = d.layer_id
        LEFT JOIN documents orig ON orig.id = d.reversal_of
        JOIN postings p ON p.document_id = docs.id
        LEFT JOIN currencies c ON c.id = p.currency_id
        ORDER BY docs.doc_date, docs.number, p.line_no
        """,
        params,
    ).fetchall()
    result: list[tuple[Row, list[Row]]] = []
    for r in rows:
        if not result or result[-1][0]["doc_id"] != r["doc_id"]:
            result.append((r, []))
        result[-1][1].append(r)
    return result


def _transaction_line(doc: Row) -> str:
    line = f"{doc['doc_date']} ({doc['number']}) {_clean(doc['memo'], '|')}".rstrip()
    tags = []
    if doc["reversal_of"] is not None:
        tags.append(f"{tr('сторно')}: {doc['reversal_of']}")
    if doc["layer"] != "common":
        tags.append(f"{tr('слой')}: {_clean(doc['layer_name'], ',')}")
    return line + ("  ; " + ", ".join(tags) if tags else "")


def _posting_line(account: str, minor: int) -> str:
    return f"    {account}  {_amount(minor)} {BASE}"


def _tags(p: Row, side: str, values: dict[int, tuple[str, str]]) -> list[tuple[str, str]]:
    """Subconto of this side; the posting's own e-qaimə and memo go on its debit line."""
    tags = [values[p[f"{side}_sc{i}"]] for i in (1, 2, 3) if p[f"{side}_sc{i}"] is not None]
    if side == "ct":
        return tags
    if p["invoice"]:
        label = tr("декларация") if p["invoice_kind"] == "customs" else "e-qaimə"
        tags.append((label, _clean(p["invoice"], ",")))
    if p["line_memo"]:
        tags.append((tr("примечание"), _clean(p["line_memo"], ",")))
    return tags
