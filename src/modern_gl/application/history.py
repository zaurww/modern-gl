"""A document's story from the audit trail (D96): who did what and when, and why — the
reason told when a posted document was unposted or deleted. Nothing new is stored."""

from __future__ import annotations

import json
from dataclasses import dataclass

from modern_gl.infrastructure.db import Connection

# audit action -> what the user reads (Russian, for tr())
ACTIONS: dict[str, str] = {
    "create_draft": "Создан черновик",
    "update_draft": "Черновик изменён",
    "post": "Проведён",
    "repost": "Исправлен и проведён",
    "reverse": "Проведено сторно",
    "unpost": "Проведение отменено",
    "delete": "Удалён",
}


@dataclass(frozen=True)
class HistoryEvent:
    at: str  # UTC, ISO, as in audit_events
    actor: str
    action: str  # Russian, for tr()
    reason: str


def document_history(conn: Connection, company_id: int, doc_id: int) -> list[HistoryEvent]:
    """The document's events, oldest first."""
    rows = conn.execute(
        """
        SELECT at, actor, action, details FROM audit_events
        WHERE company_id = ? AND entity = 'document' AND entity_id = ?
        ORDER BY id
        """,
        (company_id, doc_id),
    ).fetchall()
    return [
        HistoryEvent(
            r["at"],
            r["actor"],
            ACTIONS.get(str(r["action"]), str(r["action"])),
            reason_of(r["details"]),
        )
        for r in rows
    ]


def reason_of(details: str | None) -> str:
    """The reason kept in an event's details ('' when none was told)."""
    if not details:
        return ""
    data = json.loads(details)
    return data.get("reason", "") if isinstance(data, dict) else ""
