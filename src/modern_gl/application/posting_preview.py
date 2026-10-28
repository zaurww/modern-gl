"""The postings a module's document makes, to check them by eye: its stored ones, or the
ones it would make — its own saving and posting run and rolled back (`dry_run`), so what
is shown and what is posted cannot differ. A module's GL documents are found through
`document_owners` (D75): the core knows no module's tables."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import Connection, Row, dry_run

SIDES = ("dt", "ct")


@dataclass(frozen=True)
class PreviewPosting:
    doc_date: str
    debit: str  # the account's code, its name when it has none
    debit_name: str
    debit_subconto: tuple[str, ...]  # the names of the filled ones
    credit: str
    credit_name: str
    credit_subconto: tuple[str, ...]
    amount: int  # minor units
    currency: str | None  # its code; None in manats
    currency_amount: int | None
    memo: str
    invoice: str


@dataclass(frozen=True)
class PostingPreview:
    postings: list[PreviewPosting] = field(default_factory=list)
    error: str = ""  # why it would not post: nothing is shown then

    @property
    def total(self) -> int:
        return sum(p.amount for p in self.postings)


def _subconto_joins() -> tuple[str, str]:
    names = ", ".join(f"{side}{n}.name AS {side}_name{n}" for side in SIDES for n in (1, 2, 3))
    joins = " ".join(
        f"LEFT JOIN subconto_values {side}{n} "
        f"ON {side}{n}.company_id = p.company_id AND {side}{n}.id = p.{side}_sc{n}"
        for side in SIDES
        for n in (1, 2, 3)
    )
    return names, joins


def owned_postings(
    conn: Connection, company_id: int, module: str, owner_ids: Collection[int]
) -> list[PreviewPosting]:
    """The postings of the GL documents the module's documents `owner_ids` made, in date
    order, line by line."""
    if not owner_ids:
        return []
    marks = ", ".join("?" * len(owner_ids))
    documents = conn.execute(
        "SELECT document_id FROM document_owners WHERE company_id = ? AND module = ? "
        f"AND role = 'made' AND owner_id IN ({marks}) ORDER BY document_id",
        (company_id, module, *owner_ids),
    ).fetchall()
    return _postings(conn, company_id, [row[0] for row in documents])


def gl_postings(conn: Connection, company_id: int, document_id: int) -> list[PreviewPosting]:
    """The postings of one GL document (a row of the journal or of a bank statement)."""
    return _postings(conn, company_id, [document_id])


def _postings(conn: Connection, company_id: int, document_ids: list[int]) -> list[PreviewPosting]:
    if not document_ids:
        return []
    marks = ", ".join("?" * len(document_ids))
    names, joins = _subconto_joins()
    rows = conn.execute(
        f"""
        SELECT d.doc_date, d.id AS document_id, p.line_no,
               COALESCE(NULLIF(TRIM(da.code), ''), da.name) AS debit, da.name AS debit_name,
               COALESCE(NULLIF(TRIM(ca.code), ''), ca.name) AS credit, ca.name AS credit_name,
               p.amount, c.code AS currency, p.currency_amount, p.memo, p.invoice, {names}
        FROM documents d
        JOIN postings p ON p.company_id = d.company_id AND p.document_id = d.id
        JOIN accounts da ON da.company_id = p.company_id AND da.id = p.debit_account_id
        JOIN accounts ca ON ca.company_id = p.company_id AND ca.id = p.credit_account_id
        LEFT JOIN currencies c ON c.company_id = p.company_id AND c.id = p.currency_id
        {joins}
        WHERE d.company_id = ? AND d.id IN ({marks})
        ORDER BY d.doc_date, d.id, p.line_no
        """,
        (company_id, *document_ids),
    ).fetchall()
    return [
        PreviewPosting(
            doc_date=r["doc_date"],
            debit=r["debit"],
            debit_name=r["debit_name"],
            debit_subconto=_filled(r, "dt"),
            credit=r["credit"],
            credit_name=r["credit_name"],
            credit_subconto=_filled(r, "ct"),
            amount=r["amount"],
            currency=r["currency"],
            currency_amount=r["currency_amount"],
            memo=r["memo"],
            invoice=r["invoice"] or "",
        )
        for r in rows
    ]


def _filled(row: Row, side: str) -> tuple[str, ...]:
    return tuple(name for n in (1, 2, 3) if (name := row[f"{side}_name{n}"]) is not None)


def preview_postings(
    conn: Connection, company_id: int, module: str, write: Callable[[], Collection[int]]
) -> PostingPreview:
    """What posting would make: `write()` saves and posts the module's documents as the
    page would (its scenario methods) and gives their ids; it runs and is rolled back.
    A refusal is the preview's `error` — the page shows why it would not post."""
    try:
        with dry_run(conn):
            return PostingPreview(owned_postings(conn, company_id, module, write()))
    except (LedgerError, ValueError) as e:
        return PostingPreview(error=str(e))
