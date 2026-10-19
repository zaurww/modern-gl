"""Read models for the UI: companies, journal list, a single document."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from modern_gl.domain.errors import NotFoundError


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
            return "Черновик"
        if self.reversal_of_number is not None:
            return f"Сторно №{self.reversal_of_number}"
        if self.reversed_by_number is not None:
            return f"Сторнирован №{self.reversed_by_number}"
        return "Проведён"


@dataclass
class PostingData:
    debit_account_id: int
    credit_account_id: int
    amount: int
    debit_subconto: tuple[int | None, int | None, int | None]
    credit_subconto: tuple[int | None, int | None, int | None]
    memo: str


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
    postings: list[PostingData] = field(default_factory=list)


def list_companies(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [
        (r["id"], r["name"]) for r in conn.execute("SELECT id, name FROM companies ORDER BY id")
    ]


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
               (SELECT r.id FROM documents r WHERE r.reversal_of = d.id) AS reversed_by
        FROM documents d JOIN layers l ON l.id = d.layer_id
        WHERE d.company_id = ? AND d.id = ?
        """,
        (company_id, doc_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"документ {doc_id} не найден")
    doc = DocumentData(**dict(row))
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
            )
        )
    return doc
