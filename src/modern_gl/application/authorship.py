"""Who entered and who posted a GL document (D82). Nothing new is stored: every write to a
document is already in the audit trail with its actor and time, so it is read from there."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

POSTED = ("post", "repost", "reverse")
# the actions of the one who enters a document; unpost and delete are not authorship
AUTHORED = ("create_draft", "update_draft", *POSTED)


@dataclass(frozen=True)
class DocumentAuthors:
    entered_by: str
    entered_at: str  # UTC, ISO, as in audit_events
    posted_by: str | None  # None: a draft (never posted, or unposted since)
    posted_at: str | None


def document_authors(conn: Connection, company_id: int, doc_id: int) -> DocumentAuthors | None:
    """None when the trail knows nothing of the document (another company's id…)."""
    events = conn.execute(
        """
        SELECT actor, at, action FROM audit_events
        WHERE company_id = ? AND entity = 'document' AND entity_id = ?
        ORDER BY id
        """,
        (company_id, doc_id),
    ).fetchall()
    if not events:
        return None
    posted = None
    for event in events:
        if event["action"] in POSTED:
            posted = event
        elif event["action"] == "unpost":
            posted = None
    first = events[0]
    return DocumentAuthors(
        first["actor"],
        first["at"],
        posted["actor"] if posted else None,
        posted["at"] if posted else None,
    )


def local_time(at: str) -> str:
    """An audit time (UTC) as the user's clock shows it: 15.01.2026 14:32."""
    return datetime.fromisoformat(at).astimezone().strftime("%d.%m.%Y %H:%M")


def authors_text(a: DocumentAuthors) -> tuple[str, str]:
    """One quiet line for the document's head, and the full story for its tooltip."""
    entered = tr("Ввёл: {who}, {when}", who=a.entered_by, when=local_time(a.entered_at))
    if a.posted_by is None or a.posted_at is None:
        return tr("Ввёл {who} · {when}", who=a.entered_by, when=local_time(a.entered_at)), entered
    posted = tr("Провёл: {who}, {when}", who=a.posted_by, when=local_time(a.posted_at))
    when = local_time(a.posted_at)
    if a.posted_by == a.entered_by:
        line = tr("Провёл {who} · {when}", who=a.posted_by, when=when)
    else:
        line = tr(
            "Ввёл {entered} · провёл {posted} · {when}",
            entered=a.entered_by,
            posted=a.posted_by,
            when=when,
        )
    return line, f"{entered}\n{posted}"


def journal_authors(conn: Connection, company_id: int) -> dict[int, str]:
    """For the journal: each document → who entered or posted it last."""
    marks = ", ".join("?" * len(AUTHORED))
    rows = conn.execute(
        f"""
        SELECT a.entity_id, a.actor FROM audit_events a
        JOIN (SELECT MAX(id) AS last FROM audit_events
              WHERE company_id = ? AND entity = 'document' AND action IN ({marks})
              GROUP BY entity_id) m ON m.last = a.id
        """,
        (company_id, *AUTHORED),
    )
    return {r["entity_id"]: r["actor"] for r in rows}
