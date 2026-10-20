"""Read models for the UI: companies, journal list, a single document."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import sort_key, tr


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
        )


def list_companies(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [
        (r["id"], r["name"]) for r in conn.execute("SELECT id, name FROM companies ORDER BY id")
    ]


def company_name(conn: sqlite3.Connection, company_id: int) -> str:
    row = conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()
    if row is None:
        raise NotFoundError(tr("компания {id} не найдена", id=company_id))
    return row[0]


def list_layers(conn: sqlite3.Connection, company_id: int) -> list[tuple[str, str]]:
    return [
        (r["code"], r["name"])
        for r in conn.execute(
            "SELECT code, name FROM layers WHERE company_id = ? ORDER BY id", (company_id,)
        )
    ]


def list_documents(conn: sqlite3.Connection, company_id: int) -> list[DocumentSummary]:
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
        WHERE d.company_id = ?
        GROUP BY d.id
        ORDER BY d.doc_date, d.number
        """,
        (company_id,),
    ).fetchall()
    return [DocumentSummary(**dict(r)) for r in rows]


def load_document(conn: sqlite3.Connection, company_id: int, doc_id: int) -> DocumentData:
    row = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.memo, l.code AS layer, d.status, d.reversal_of,
               (SELECT r.id FROM documents r WHERE r.reversal_of = d.id) AS reversed_by,
               COALESCE(c.closed_through >= d.doc_date, 0) AS closed,
               i.id AS inventory_document_id, i.number AS inventory_number
        FROM documents d
        JOIN layers l ON l.id = d.layer_id
        JOIN companies c ON c.id = d.company_id
        LEFT JOIN inventory_documents i ON i.gl_document_id = d.id
        WHERE d.company_id = ? AND d.id = ?
        """,
        (company_id, doc_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(tr("документ {id} не найден", id=doc_id))
    doc = DocumentData(**{**dict(row), "closed": bool(row["closed"])})
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


def list_templates(conn: sqlite3.Connection, company_id: int) -> list[TemplateData]:
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


def load_template(conn: sqlite3.Connection, company_id: int, template_id: int) -> TemplateData:
    found = next((t for t in list_templates(conn, company_id) if t.id == template_id), None)
    if found is None:
        raise NotFoundError(tr("шаблон не найден"))
    return found


def recent_subconto(
    conn: sqlite3.Connection, company_id: int, account_id: int, position: int, limit: int = 8
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


def last_memo(conn: sqlite3.Connection, company_id: int, debit: int, credit: int) -> str:
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
class OpeningBalanceDocument:
    document_id: int
    effective_date: str  # the morning the balances take effect; the document is a day earlier
    status: str


def opening_document(conn: sqlite3.Connection, company_id: int) -> OpeningBalanceDocument | None:
    row = conn.execute(
        "SELECT o.document_id, o.effective_date, d.status FROM opening_balance_documents o "
        "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ?",
        (company_id,),
    ).fetchone()
    return OpeningBalanceDocument(**dict(row)) if row is not None else None


def is_opening_document(conn: sqlite3.Connection, company_id: int, document_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM opening_balance_documents WHERE company_id = ? AND document_id = ?",
            (company_id, document_id),
        ).fetchone()
        is not None
    )
