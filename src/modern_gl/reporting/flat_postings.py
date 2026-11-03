"""«Проводки для Excel»: every posting of a period as one flat line, every dimension
its own field — the account with its class and top-level account, each subconto under
the name of its kind (a column «Контрагенты», not «субконто 1»), the book, the module
that made the document, who posted it. With the balances before the period, so a pivot
table over the lines gives closing balances, not only turnovers. Nothing is grouped
here: Excel does that (`flat_excel.py` lays the sheets out)."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.authorship import journal_authors
from modern_gl.application.books import COMMON, FROM, book_params, docs_cte
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import _accounts

# the modules that make GL documents (`document_owners`, role 'made'), by their name there
SOURCES = {"inventory": N_("Склад"), "bank": N_("Банк"), "conversion": N_("Конвертация")}
_LINES_CTE = docs_cte("d.id, d.doc_date, d.number, d.memo, l.name AS layer", start=FROM)
_HISTORY_CTE = docs_cte("d.id, d.doc_date")


@dataclass(frozen=True)
class Kind:
    """A kind of subconto the chart uses: a column of its own."""

    id: int
    name: str
    folders: bool = False  # some of its elements lie in a folder (D60)
    tags: bool = False  # some of its elements carry a tag


@dataclass(frozen=True)
class Value:
    name: str
    folder: str = ""
    tags: str = ""


@dataclass(frozen=True)
class Side:
    """One side of a posting: the account and its subconto by kind."""

    account_id: int
    code: str
    name: str
    account_class: str  # asset, liability, equity, revenue, expense or ""
    top_code: str  # the account at the top of its branch
    top_name: str
    values: dict[int, Value] = field(default_factory=dict[int, Value])  # kind id -> value

    def value(self, kind_id: int) -> Value | None:
        return self.values.get(kind_id)


@dataclass(frozen=True)
class FlatLine:
    document_id: int
    doc_date: str
    number: int
    source: str  # «Банк», «Склад №12», «Проводка»
    memo: str
    line_memo: str
    debit: Side
    credit: Side
    amount: int
    currency: str
    currency_amount: int | None
    layer: str
    invoice: str
    invoice_kind: str
    author: str


@dataclass(frozen=True)
class OpeningLine:
    """A balance before the period: of an account and its subconto (Dt +, Kt −)."""

    side: Side
    net: int


@dataclass
class FlatPostings:
    date_from: str
    date_to: str
    kinds: list[Kind]
    lines: list[FlatLine]
    opening: list[OpeningLine]

    @property
    def total(self) -> int:
        """The turnover of the period — Dt and Kt alike, each posting is balanced."""
        return sum(line.amount for line in self.lines)


def flat_postings(
    conn: Connection, company_id: int, date_from, date_to, layers=COMMON
) -> FlatPostings:
    params = book_params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    values = _values(conn, company_id)
    kinds = _kinds(conn, company_id, values)
    sides: dict[tuple, Side] = {}

    def side(account_id: int, sc: tuple[int | None, ...]) -> Side:
        key = (account_id, *sc)
        if key not in sides:
            sides[key] = _side(accounts, values, account_id, sc)
        return sides[key]

    authors = journal_authors(conn, company_id)
    lines = [
        FlatLine(
            document_id=r["document_id"],
            doc_date=r["doc_date"],
            number=r["number"],
            source=_source(r["source"], r["owner_number"]),
            memo=r["memo"],
            line_memo=r["line_memo"],
            debit=side(r["debit_account_id"], (r["dt_sc1"], r["dt_sc2"], r["dt_sc3"])),
            credit=side(r["credit_account_id"], (r["ct_sc1"], r["ct_sc2"], r["ct_sc3"])),
            amount=r["amount"],
            currency=r["currency"] or "",
            currency_amount=r["currency_amount"] if r["currency"] else None,
            layer=r["layer"],
            invoice=r["invoice"] or "",
            invoice_kind=r["invoice_kind"] or "",
            author=authors.get(r["document_id"], ""),
        )
        for r in _line_rows(conn, params)
    ]
    opening = [
        OpeningLine(side(r["account_id"], (r["sc1"], r["sc2"], r["sc3"])), r["net"])
        for r in _opening_rows(conn, params)
    ]
    return FlatPostings(params["date_from"], params["date_to"], kinds, lines, opening)


def _line_rows(conn: Connection, params: dict) -> list[Row]:
    """The postings of the period, in the order of the journal; the module that made the
    document — from the `document_owners` view, the one place that knows (D75)."""
    return conn.execute(
        f"""
        WITH {_LINES_CTE},
        made AS (
            SELECT document_id, MIN(module) AS module, MIN(owner_number) AS owner_number
            FROM document_owners
            WHERE company_id = :company_id AND role = 'made'
            GROUP BY document_id
        )
        SELECT docs.id AS document_id, docs.doc_date, docs.number, docs.memo, docs.layer,
               p.debit_account_id, p.credit_account_id, p.amount,
               p.dt_sc1, p.dt_sc2, p.dt_sc3, p.ct_sc1, p.ct_sc2, p.ct_sc3,
               p.currency_amount, c.code AS currency, p.invoice, p.invoice_kind,
               p.memo AS line_memo, made.module AS source, made.owner_number
        FROM postings p
        JOIN docs ON docs.id = p.document_id
        LEFT JOIN currencies c ON c.id = p.currency_id
        LEFT JOIN made ON made.document_id = p.document_id
        WHERE p.company_id = :company_id
        ORDER BY docs.doc_date, docs.number, p.line_no
        """,
        params,
    ).fetchall()


def _opening_rows(conn: Connection, params: dict) -> list[Row]:
    """Balances before the period by account and subconto, Dt + / Kt −; zero left out."""
    return conn.execute(
        f"""
        WITH {_HISTORY_CTE},
        moves AS (
            SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc1, p.dt_sc2 AS sc2,
                   p.dt_sc3 AS sc3, p.amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id AND docs.doc_date < :date_from
            UNION ALL
            SELECT p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, -p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id AND docs.doc_date < :date_from
        )
        SELECT account_id, sc1, sc2, sc3, SUM(net) AS net
        FROM moves
        GROUP BY account_id, sc1, sc2, sc3
        HAVING SUM(net) <> 0
        ORDER BY account_id, sc1, sc2, sc3
        """,
        params,
    ).fetchall()


def _values(conn: Connection, company_id: int) -> dict[int, tuple[int, Value]]:
    """Subconto element id -> (kind id, its name, folder and tags)."""
    rows = conn.execute(
        """
        SELECT v.id, v.kind_id, v.name, g.name AS folder,
               (SELECT string_agg(t.name, ', ') FROM subconto_value_tags vt
                JOIN tags t ON t.id = vt.tag_id
                WHERE vt.company_id = v.company_id AND vt.value_id = v.id) AS tags
        FROM subconto_values v
        LEFT JOIN subconto_values g ON g.company_id = v.company_id AND g.id = v.parent_id
        WHERE v.company_id = ?
        """,
        (company_id,),
    )
    return {
        r["id"]: (r["kind_id"], Value(r["name"], r["folder"] or "", r["tags"] or "")) for r in rows
    }


def _kinds(conn: Connection, company_id: int, values: dict[int, tuple[int, Value]]) -> list[Kind]:
    """The kinds some account keeps a subconto of, in the order of the directory."""
    rows = conn.execute(
        """
        SELECT k.id, k.name FROM subconto_kinds k
        WHERE k.company_id = ? AND EXISTS (
            SELECT 1 FROM accounts a
            WHERE a.company_id = k.company_id
              AND k.id IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
        )
        ORDER BY k.id
        """,
        (company_id,),
    ).fetchall()
    return [
        Kind(
            r["id"],
            r["name"],
            folders=any(k == r["id"] and v.folder for k, v in values.values()),
            tags=any(k == r["id"] and v.tags for k, v in values.values()),
        )
        for r in rows
    ]


def _side(
    accounts: dict[int, Row],
    values: dict[int, tuple[int, Value]],
    account_id: int,
    sc: tuple[int | None, ...],
) -> Side:
    a = accounts[account_id]
    top = a
    while top["parent_id"] is not None:
        top = accounts[top["parent_id"]]
    return Side(
        account_id=account_id,
        code=a["code"] or "",
        name=a["name"],
        account_class=a["account_class"] or "",
        top_code=top["code"] or "",
        top_name=top["name"],
        values={values[v][0]: values[v][1] for v in sc if v is not None and v in values},
    )


def _source(module: str | None, owner_number: object) -> str:
    if module is None:
        return tr("Проводка")
    name = tr(SOURCES.get(module, module))
    return f"{name} №{owner_number}" if owner_number else name
