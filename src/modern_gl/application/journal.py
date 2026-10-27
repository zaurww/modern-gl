"""The journal read in pages (D168): a large company's year is tens of
thousands of documents, so the page reads the 500 around the one shown and the rest as
the list is scrolled. Pages follow the journal's order (date, number) by its key, not by
an offset, and the search is a condition of the query: it finds what was not read yet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from modern_gl.application.authorship import AUTHORED
from modern_gl.application.queries import DocumentSummary
from modern_gl.domain.money import to_minor
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection

PAGE = 500  # documents read at a time
Key = tuple[str, int]  # (doc_date, number): where a document stands in the journal
Direction = Literal["ASC", "DESC"]  # the order a page is read in — a word of SQL, not a value


@dataclass(frozen=True)
class JournalFilter:
    company_id: int
    date_from: str | None = None
    date_to: str | None = None
    text: str = ""  # searched as the journal shows it: memo, number, date, sum, book, status
    layer_names: tuple[tuple[str, str], ...] = ()  # (code, name) of the company's books


@dataclass(frozen=True)
class Rows:
    """Documents in the journal's order, and whether more stand beyond them."""

    docs: list[DocumentSummary]
    more: bool


def key_of(doc: DocumentSummary) -> Key:
    return doc.doc_date, doc.number


def document_key(conn: Connection, company_id: int, doc_id: int) -> Key | None:
    row = conn.execute(
        "SELECT doc_date, number FROM documents WHERE company_id = ? AND id = ?",
        (company_id, doc_id),
    ).fetchone()
    return (row["doc_date"], row["number"]) if row else None


def documents_before(
    conn: Connection,
    f: JournalFilter,
    key: Key | None,
    limit: int = PAGE,
    *,
    including: bool = False,
) -> Rows:
    """The last `limit` documents before `key` (with it if `including`; None — up to the
    end), in the journal's order."""
    sign = "<=" if including else "<"
    return _rows(conn, f, None if key is None else (sign, key), "DESC", limit)


def documents_after(conn: Connection, f: JournalFilter, key: Key, limit: int = PAGE) -> Rows:
    """The first `limit` documents after `key`."""
    return _rows(conn, f, (">", key), "ASC", limit)


def _rows(
    conn: Connection,
    f: JournalFilter,
    bound: tuple[str, Key] | None,
    direction: Direction,
    limit: int,
) -> Rows:
    where = ["d.company_id = :company_id"]
    params: dict[str, object] = {"company_id": f.company_id, "limit": limit + 1}
    if f.date_from:
        where.append("d.doc_date >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        where.append("d.doc_date <= :date_to")
        params["date_to"] = f.date_to
    if bound is not None:
        sign, (key_date, key_number) = bound
        params |= {"key_date": key_date, "key_number": key_number}
        where.append(f"(d.doc_date, d.number) {sign} (:key_date, :key_number)")
    if text := fold(f.text.strip()):
        where.append(_search(f, text, params))
    rows = conn.execute(
        f"""
        WITH page AS (
            SELECT d.id FROM documents d
            WHERE {" AND ".join(where)}
            ORDER BY d.doc_date {direction}, d.number {direction}
            LIMIT :limit
        )
        SELECT d.id, d.number, d.doc_date, d.memo, l.code AS layer, d.status,
               o.number AS reversal_of_number, r.number AS reversed_by_number,
               COALESCE(SUM(ABS(p.amount)), 0) AS total, COUNT(p.id) AS lines
        FROM page
        JOIN documents d ON d.id = page.id
        JOIN layers l ON l.id = d.layer_id
        LEFT JOIN documents o ON o.id = d.reversal_of
        LEFT JOIN documents r ON r.reversal_of = d.id
        LEFT JOIN postings p ON p.document_id = d.id
        GROUP BY d.id, d.number, d.doc_date, d.memo, l.code, d.status, o.number, r.number
        ORDER BY d.doc_date {direction}, d.number {direction}
        """,
        params,
    ).fetchall()
    docs = [DocumentSummary(**dict(r)) for r in rows[:limit]]
    if direction == "DESC":
        docs.reverse()
    return Rows(docs, len(rows) > limit)


# the folded text in the memo, the number or the date as the journal shows it (D86)
_TEXT = """
    fold(d.memo) LIKE :text ESCAPE '\\'
    OR CAST(d.number AS TEXT) LIKE :text ESCAPE '\\'
    OR substr(d.doc_date, 9, 2) || '.' || substr(d.doc_date, 6, 2) || '.'
       || substr(d.doc_date, 1, 4) LIKE :text ESCAPE '\\'"""
# the total the journal shows, or the sum of one of the lines
_AMOUNT = """
    OR (SELECT COALESCE(SUM(ABS(p.amount)), 0) FROM postings p
        WHERE p.company_id = d.company_id AND p.document_id = d.id) = :amount
    OR EXISTS (SELECT 1 FROM postings p
               WHERE p.company_id = d.company_id AND p.document_id = d.id
                 AND ABS(p.amount) = :amount)"""
# what the column «Статус» says, by the kind of document
_STATUS = {
    "draft": "d.status = 'draft'",
    "reversal": "d.reversal_of IS NOT NULL",
    "reversed": "EXISTS (SELECT 1 FROM documents r"
    " WHERE r.company_id = d.company_id AND r.reversal_of = d.id)",
    "posted": "d.status = 'posted'",
}


def _status_names() -> dict[str, str]:
    return {
        "draft": tr("Черновик"),
        "reversal": tr("Сторно №{n}", n="").rstrip("№ "),
        "reversed": tr("Сторнирован №{n}", n="").rstrip("№ "),
        "posted": tr("Проведён"),
    }


def _search(f: JournalFilter, text: str, params: dict[str, object]) -> str:
    """What the search box finds: what any column of the journal shows — as the list
    filtered its rows before it was read in pages — but in the whole year, not only in
    the rows read so far."""
    params["text"] = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    params["text"] += "%"
    found = [_TEXT]
    if (amount := _amount(text)) is not None:
        params["amount"] = amount
        found.append(_AMOUNT)
    codes = [code for code, name in f.layer_names if code != "common" and text in fold(name)]
    if codes:
        names = [f":layer{n}" for n in range(len(codes))]
        params |= dict(zip((n[1:] for n in names), codes, strict=True))
        found.append(
            "OR d.layer_id IN (SELECT id FROM layers WHERE company_id = :company_id"
            f" AND code IN ({', '.join(names)}))"
        )
    found += [f"OR {_STATUS[kind]}" for kind, name in _status_names().items() if text in fold(name)]
    return "(" + "\n".join(found) + ")"


def _amount(text: str) -> int | None:
    """The searched text as a sum of money (1 234,50 or 1234.5), or None."""
    plain = text.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not plain or not any(ch.isdigit() for ch in plain):
        return None
    try:
        amount = to_minor(plain)
    except ValueError:
        return None
    return amount if amount > 0 else None


def page_authors(conn: Connection, company_id: int, doc_ids: list[int]) -> dict[int, str]:
    """Who entered or posted each of these documents last (D82)."""
    if not doc_ids:
        return {}
    marks = ", ".join("?" * len(AUTHORED))
    ids = ", ".join("?" * len(doc_ids))
    rows = conn.execute(
        f"""
        SELECT a.entity_id, a.actor FROM audit_events a
        JOIN (SELECT MAX(id) AS last FROM audit_events
              WHERE company_id = ? AND entity = 'document' AND action IN ({marks})
                AND entity_id IN ({ids})
              GROUP BY entity_id) m ON m.last = a.id
        """,
        (company_id, *AUTHORED, *doc_ids),
    )
    return {r["entity_id"]: r["actor"] for r in rows}


def several_authors(conn: Connection, company_id: int) -> bool:
    """More than one person entered or posted the company's documents last: the journal
    shows its column «Автор»."""
    marks = ", ".join("?" * len(AUTHORED))
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT a.actor) FROM audit_events a
        JOIN (SELECT MAX(id) AS last FROM audit_events
              WHERE company_id = ? AND entity = 'document' AND action IN ({marks})
              GROUP BY entity_id) m ON m.last = a.id
        """,
        (company_id, *AUTHORED),
    ).fetchone()
    return row[0] > 1
