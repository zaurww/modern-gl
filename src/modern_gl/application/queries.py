"""Read models for the UI: companies, journal list, a single document."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from itertools import chain
from typing import Any

from modern_gl.application.common import company_row
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import fold, sort_key, tr
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class DocumentSummary:
    id: int
    number: int
    doc_date: str
    memo: str
    layer: str
    status: str
    reversal_of_number: int | None
    reversed_by_number: int | None
    total: int
    lines: int

    @property
    def status_text(self) -> str:
        if self.status == "draft":
            return tr("Черновик")
        if self.reversal_of_number is not None:
            return tr("Сторно №{n}", n=self.reversal_of_number)
        if self.reversed_by_number is not None:
            return tr("Сторнирован №{n}", n=self.reversed_by_number)
        return tr("Проведён")


@dataclass
class PostingData:
    debit_account_id: int
    credit_account_id: int
    amount: int
    debit_subconto: tuple[int | None, int | None, int | None]
    credit_subconto: tuple[int | None, int | None, int | None]
    memo: str
    currency_id: int | None = None
    currency_amount: int | None = None
    invoice: str = ""  # e-qaimə number
    invoice_kind: str = ""  # "customs": the number of a customs declaration
    pays_vat: bool = False  # paid to the supplier's ƏDV deposit from a bank account


@dataclass
class DocumentData:
    id: int
    number: int
    doc_date: str
    memo: str
    layer: str
    status: str
    reversal_of: int | None
    reversed_by: int | None
    closed: bool = False  # dated in a closed period: only a storno can correct it
    # made by a warehouse document (id, number): it is corrected there, not here
    inventory_document_id: int | None = None
    inventory_number: int | None = None
    conversion_id: int | None = None  # made by a currency conversion: corrected there
    bank_operation_id: int | None = None  # made by a bank operation: corrected there
    used: bool = False  # a module takes it in (a batch's expense): released there first
    postings: list[PostingData] = field(default_factory=list)

    @property
    def editable(self) -> bool:
        """Whether the document can be changed in place (a posted one: as in 1C)."""
        if self.status != "posted":
            return True
        return (
            not self.closed
            and self.reversal_of is None
            and self.reversed_by is None
            and self.inventory_document_id is None
            and self.conversion_id is None
            and self.bank_operation_id is None
            and not self.used
        )


def company_name(conn: Connection, company_id: int) -> str:
    return company_row(conn, company_id)["name"]


def parallel_books(conn: Connection, company_id: int) -> bool:
    """Whether the company keeps IFRS and tax books beside the common one (D63)."""
    row = conn.execute("SELECT parallel_books FROM companies WHERE id = ?", (company_id,))
    return bool(row.fetchone()[0])


def company_tax_id(conn: Connection, company_id: int) -> str | None:
    """The company's own VÖEN (D113); None — not known yet."""
    row = conn.execute("SELECT tax_id FROM companies WHERE id = ?", (company_id,))
    return row.fetchone()[0]


def company_mode(conn: Connection, company_id: int) -> str:
    """How the company is kept (D90): FULL, or STOCK_ONLY — only the warehouse is shown."""
    row = conn.execute("SELECT mode FROM companies WHERE id = ?", (company_id,))
    return row.fetchone()[0]


def list_layers(conn: Connection, company_id: int) -> list[tuple[str, str]]:
    return [
        (r["code"], r["name"])
        for r in conn.execute(
            "SELECT code, name FROM layers WHERE company_id = ? ORDER BY id", (company_id,)
        )
    ]


def list_documents(
    conn: Connection, company_id: int, date_from: str | None = None, date_to: str | None = None
) -> list[DocumentSummary]:
    """The journal: every document, or those dated within the period."""
    rows = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.memo, l.code AS layer, d.status,
               o.number AS reversal_of_number, r.number AS reversed_by_number,
               COALESCE(SUM(ABS(p.amount)), 0) AS total, COUNT(p.id) AS lines
        FROM documents d
        JOIN layers l ON l.id = d.layer_id
        LEFT JOIN documents o ON o.id = d.reversal_of
        LEFT JOIN documents r ON r.reversal_of = d.id
        LEFT JOIN postings p ON p.document_id = d.id
        WHERE d.company_id = :company_id
          AND (:date_from IS NULL OR d.doc_date >= :date_from)
          AND (:date_to IS NULL OR d.doc_date <= :date_to)
        GROUP BY d.id
        ORDER BY d.doc_date, d.number
        """,
        {"company_id": company_id, "date_from": date_from, "date_to": date_to},
    ).fetchall()
    return [DocumentSummary(**dict(r)) for r in rows]


def document_years(conn: Connection, company_id: int) -> list[int]:
    """The years from the first document's to the last's, the latest first: the journal
    shows one of them (debt 6: not all of a large company's documents at once)."""
    first, last = conn.execute(
        "SELECT MIN(doc_date), MAX(doc_date) FROM documents WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    if first is None:
        return []
    return list(range(int(str(last)[:4]), int(str(first)[:4]) - 1, -1))


def document_year(conn: Connection, company_id: int, doc_id: int) -> int | None:
    """The year of a document's date (None: there is no such document)."""
    row = conn.execute(
        "SELECT doc_date FROM documents WHERE company_id = ? AND id = ?", (company_id, doc_id)
    ).fetchone()
    return int(str(row[0])[:4]) if row else None


@dataclass(frozen=True)
class FoundDocument:
    id: int
    number: int
    doc_date: str
    memo: str
    status: str


def find_documents(
    conn: Connection, company_id: int, text: str, limit: int = 8
) -> list[FoundDocument]:
    """Ctrl+K (D86): a document by its number («15», «№15»), or by words of its title
    (letters folded: «odenis» finds «Ödəniş») — the latest first. The rows are read one
    by one, newest first, until `limit` are found: no list of all documents is built."""
    text = text.strip().lstrip("№#").strip()
    if not text:
        return []
    if text.isdigit():
        row = conn.execute(
            "SELECT id, number, doc_date, memo, status FROM documents "
            "WHERE company_id = ? AND number = ?",
            (company_id, int(text)),
        ).fetchone()
        return [FoundDocument(**dict(row))] if row else []
    words = fold(text).split()
    cursor = conn.execute(
        "SELECT id, number, doc_date, memo, status FROM documents "
        "WHERE company_id = ? ORDER BY doc_date DESC, number DESC",
        (company_id,),
    )
    found: list[FoundDocument] = []
    while len(found) < limit and (rows := cursor.fetchmany(200)):
        found += [
            FoundDocument(**dict(r)) for r in rows if all(w in fold(r["memo"]) for w in words)
        ]
    return found[:limit]


def posting_count(conn: Connection, company_id: int) -> int:
    """How large the company is: its postings (the window reads large ones in the background)."""
    return conn.execute(
        "SELECT COUNT(*) FROM postings WHERE company_id = ?", (company_id,)
    ).fetchone()[0]


def journal_drafts(conn: Connection, company_id: int, day: date | str) -> list[int]:
    """Drafts of the journal dated up to the day, oldest first — not those a module made
    (a bank operation, a purchase): they are posted in their own form."""
    return [
        r["id"]
        for r in conn.execute(
            """
            SELECT d.id FROM documents d
            WHERE d.company_id = ? AND d.status = 'draft' AND d.doc_date <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM document_owners o
                  WHERE o.company_id = d.company_id AND o.document_id = d.id)
            ORDER BY d.doc_date, d.number
            """,
            (company_id, iso_date(day)),
        )
    ]


@dataclass(frozen=True)
class DocumentOwner:
    """The module document behind a GL document, from the document_owners view."""

    module: str  # 'inventory', 'conversion', 'bank', 'landed_cost'
    id: int  # the module's document: it opens there
    number: int | None  # its number, when the module numbers its documents


def document_owner(
    conn: Connection, company_id: int, document_id: int, role: str = "made"
) -> DocumentOwner | None:
    """Who made a GL document ('made': it is corrected there) or takes it in ('uses')."""
    row = conn.execute(
        "SELECT module, owner_id, owner_number FROM document_owners "
        "WHERE company_id = ? AND document_id = ? AND role = ? "
        "ORDER BY owner_number, owner_id LIMIT 1",
        (company_id, document_id, role),
    ).fetchone()
    return None if row is None else DocumentOwner(row[0], row[1], row[2])


def document_by_number(conn: Connection, company_id: int, number: int) -> int:
    row = conn.execute(
        "SELECT id FROM documents WHERE company_id = ? AND number = ?", (company_id, number)
    ).fetchone()
    if row is None:
        raise NotFoundError(tr("документ №{n} не найден", n=number))
    return row["id"]


def load_document(conn: Connection, company_id: int, doc_id: int) -> DocumentData:
    row = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.memo, l.code AS layer, d.status, d.reversal_of,
               (SELECT r.id FROM documents r WHERE r.reversal_of = d.id) AS reversed_by,
               COALESCE(c.closed_through >= d.doc_date, 0) AS closed,
               CASE WHEN m.module = 'inventory' THEN m.owner_id END AS inventory_document_id,
               CASE WHEN m.module = 'inventory' THEN m.owner_number END AS inventory_number,
               CASE WHEN m.module = 'conversion' THEN m.owner_id END AS conversion_id,
               CASE WHEN m.module = 'bank' THEN m.owner_id END AS bank_operation_id,
               EXISTS (SELECT 1 FROM document_owners o
                       WHERE o.company_id = d.company_id AND o.document_id = d.id
                         AND o.role = 'uses') AS used
        FROM documents d
        JOIN layers l ON l.id = d.layer_id
        JOIN companies c ON c.id = d.company_id
        LEFT JOIN document_owners m
            ON m.company_id = d.company_id AND m.document_id = d.id AND m.role = 'made'
        WHERE d.company_id = ? AND d.id = ?
        """,
        (company_id, doc_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(tr("документ {id} не найден", id=doc_id))
    doc = DocumentData(**{**dict(row), "closed": bool(row["closed"]), "used": bool(row["used"])})
    for p in conn.execute(
        "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (doc_id,)
    ):
        doc.postings.append(
            PostingData(
                p["debit_account_id"],
                p["credit_account_id"],
                p["amount"],
                (p["dt_sc1"], p["dt_sc2"], p["dt_sc3"]),
                (p["ct_sc1"], p["ct_sc2"], p["ct_sc3"]),
                p["memo"],
                p["currency_id"],
                p["currency_amount"],
                p["invoice"] or "",
                p["invoice_kind"] or "",
                bool(p["pays_vat"]),
            )
        )
    return doc


@dataclass
class TemplateLineData:
    debit_account_id: int | None
    credit_account_id: int | None
    formula: str
    debit_subconto: tuple[int | None, int | None, int | None]
    credit_subconto: tuple[int | None, int | None, int | None]
    memo: str


@dataclass
class TemplateData:
    id: int
    name: str
    memo: str
    lines: list[TemplateLineData] = field(default_factory=list)


@dataclass
class ReportView:
    """A saved view of a report (D-new-interactive-osv): its name and settings."""

    id: int
    name: str
    settings: dict[str, Any]


def report_views(conn: Connection, company_id: int, report: str) -> list[ReportView]:
    """The saved views of a report, alphabetically."""
    found = [
        ReportView(r["id"], r["name"], json.loads(r["settings"]))
        for r in conn.execute(
            "SELECT id, name, settings FROM report_views WHERE company_id = ? AND report = ?",
            (company_id, report),
        )
    ]
    return sorted(found, key=lambda v: sort_key(v.name))


def list_templates(conn: Connection, company_id: int) -> list[TemplateData]:
    """All entry templates with their lines, alphabetically."""
    templates = {
        r["id"]: TemplateData(r["id"], r["name"], r["memo"])
        for r in conn.execute(
            "SELECT id, name, memo FROM entry_templates WHERE company_id = ?", (company_id,)
        )
    }
    for r in conn.execute(
        "SELECT * FROM entry_template_lines WHERE company_id = ? ORDER BY template_id, line_no",
        (company_id,),
    ):
        templates[r["template_id"]].lines.append(
            TemplateLineData(
                r["debit_account_id"],
                r["credit_account_id"],
                r["formula"],
                (r["dt_sc1"], r["dt_sc2"], r["dt_sc3"]),
                (r["ct_sc1"], r["ct_sc2"], r["ct_sc3"]),
                r["memo"],
            )
        )
    return sorted(templates.values(), key=lambda t: sort_key(t.name))


def load_template(conn: Connection, company_id: int, template_id: int) -> TemplateData:
    found = next((t for t in list_templates(conn, company_id) if t.id == template_id), None)
    if found is None:
        raise NotFoundError(tr("шаблон не найден"))
    return found


def recent_subconto(
    conn: Connection, company_id: int, account_id: int, position: int, limit: int = 8
) -> list[int]:
    """Elements most recently used at a subconto position of an account, newest first."""
    if position not in (1, 2, 3):
        raise ValueError(position)
    return [
        r[0]
        for r in conn.execute(
            f"""
            SELECT value FROM (
                SELECT dt_sc{position} AS value, id FROM postings
                WHERE company_id = :c AND debit_account_id = :a AND dt_sc{position} IS NOT NULL
                UNION ALL
                SELECT ct_sc{position}, id FROM postings
                WHERE company_id = :c AND credit_account_id = :a AND ct_sc{position} IS NOT NULL
            )
            GROUP BY value ORDER BY MAX(id) DESC LIMIT :n
            """,
            {"c": company_id, "a": account_id, "n": limit},
        )
    ]


def last_memo(conn: Connection, company_id: int, debit: int, credit: int) -> str:
    """The memo of the latest posting with this Dt/Kt pair (or of its document)."""
    row = conn.execute(
        """
        SELECT CASE WHEN p.memo <> '' THEN p.memo ELSE d.memo END
        FROM postings p JOIN documents d ON d.id = p.document_id
        WHERE p.company_id = ? AND p.debit_account_id = ? AND p.credit_account_id = ?
          AND (p.memo <> '' OR d.memo <> '')
        ORDER BY p.id DESC LIMIT 1
        """,
        (company_id, debit, credit),
    ).fetchone()
    return row[0] if row else ""


@dataclass(frozen=True)
class PastPosting:
    """A posting typed before, for the quick entry line to repeat ("as the last time")."""

    debit: int
    debit_sc: tuple[int | None, int | None, int | None]
    credit: int
    credit_sc: tuple[int | None, int | None, int | None]
    amount: int
    memo: str
    currency_id: int | None = None
    currency_amount: int | None = None


def past_postings(conn: Connection, company_id: int, limit: int = 300) -> list[PastPosting]:
    """The latest posting of each Dt/Kt with its subconto, newest first: only the
    journal's own (not a module's, not a reversal, not opening balances), common book."""
    rows = conn.execute(
        """
        SELECT p.debit_account_id, p.dt_sc1, p.dt_sc2, p.dt_sc3,
               p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, p.amount,
               CASE WHEN p.memo <> '' THEN p.memo ELSE d.memo END,
               p.currency_id, p.currency_amount
        FROM postings p
        JOIN documents d ON d.company_id = p.company_id AND d.id = p.document_id
        JOIN layers l ON l.company_id = d.company_id AND l.id = d.layer_id
        WHERE p.company_id = :c AND l.code = 'common' AND d.reversal_of IS NULL
          AND p.amount > 0
          AND NOT EXISTS (SELECT 1 FROM document_owners o
                          WHERE o.company_id = d.company_id AND o.document_id = d.id)
          AND NOT EXISTS (SELECT 1 FROM opening_balance_documents b
                          WHERE b.company_id = d.company_id AND b.document_id = d.id)
        ORDER BY p.id DESC LIMIT :n
        """,
        {"c": company_id, "n": limit * 10},
    )
    found: dict[tuple, PastPosting] = {}
    for r in rows:
        past = PastPosting(r[0], (r[1], r[2], r[3]), r[4], (r[5], r[6], r[7]), *r[8:])
        key = (past.debit, past.debit_sc, past.credit, past.credit_sc)
        if key not in found:
            found[key] = past
            if len(found) == limit:
                break
    return list(found.values())


@dataclass(frozen=True)
class OpeningBalanceDocument:
    document_id: int
    effective_date: str  # the morning the balances take effect; the document is a day earlier
    status: str


def opening_document(conn: Connection, company_id: int) -> OpeningBalanceDocument | None:
    row = conn.execute(
        "SELECT o.document_id, o.effective_date, d.status FROM opening_balance_documents o "
        "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ?",
        (company_id,),
    ).fetchone()
    return OpeningBalanceDocument(**dict(row)) if row is not None else None


def is_opening_document(conn: Connection, company_id: int, document_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM opening_balance_documents WHERE company_id = ? AND document_id = ?",
            (company_id, document_id),
        ).fetchone()
        is not None
    )


def remembered_sale_subconto(
    conn: Connection,
    company_id: int,
    item_id: int | None,
    memo: str = "",
    counterparty: int | None = None,
    *,
    except_document: int | None = None,
) -> tuple[int, ...]:
    """The sale subconto (a sales group, a channel; D61) the item — a service: the line
    with the same memo — had the last time it was sold to this counterparty, else to anyone.
    () when it was never sold with any."""
    rows = conn.execute(
        """
        SELECT l.memo, l.cost_sc1, l.cost_sc2, l.cost_sc3,
               ? IN (l.offset_sc1, l.offset_sc2, l.offset_sc3) AS same_party
        FROM inventory_lines l JOIN inventory_documents d ON d.id = l.document_id
        WHERE l.company_id = ? AND d.doc_type = 'sale' AND d.id IS DISTINCT FROM ?
          AND l.item_id IS ? AND (l.item_id IS NOT NULL OR l.memo <> '')
          AND COALESCE(l.cost_sc1, l.cost_sc2, l.cost_sc3) IS NOT NULL
        ORDER BY d.doc_date DESC, d.id DESC, l.line_no
        """,
        (counterparty, company_id, except_document, item_id),
    ).fetchall()
    if item_id is None:
        wanted = fold(memo.strip())
        rows = [row for row in rows if wanted and fold(row["memo"].strip()) == wanted]
    row = next((row for row in rows if row["same_party"]), rows[0] if rows else None)
    if row is None:
        return ()
    return tuple(v for v in (row["cost_sc1"], row["cost_sc2"], row["cost_sc3"]) if v)


def remembered_expense(
    conn: Connection,
    company_id: int,
    memo: str = "",
    counterparty: int | None = None,
) -> tuple[int, tuple[int | None, int | None, int | None]] | None:
    """The expense account and its subconto a posted purchase line without an item (a
    service, a fixed asset) went to the last time: the same memo from this supplier, else
    from anyone, else this supplier's last such line (D76). None when nothing was."""
    rows = conn.execute(
        """
        SELECT l.memo, l.cost_account_id, l.cost_sc1, l.cost_sc2, l.cost_sc3,
               ? IN (l.offset_sc1, l.offset_sc2, l.offset_sc3) AS same_party
        FROM inventory_lines l
        JOIN inventory_documents d ON d.company_id = l.company_id AND d.id = l.document_id
        WHERE l.company_id = ? AND d.doc_type = 'receipt' AND d.status = 'posted'
          AND l.item_id IS NULL AND l.cost_account_id IS NOT NULL
        ORDER BY d.doc_date DESC, d.id DESC, l.line_no
        """,
        (counterparty, company_id),
    ).fetchall()
    wanted = fold(memo.strip())
    same_memo = [row for row in rows if wanted and fold(row["memo"].strip()) == wanted]
    row = next(
        chain(
            (row for row in same_memo if row["same_party"]),
            same_memo[:1],
            (row for row in rows if row["same_party"]),
        ),
        None,
    )
    if row is None:
        return None
    return row["cost_account_id"], (row["cost_sc1"], row["cost_sc2"], row["cost_sc3"])
