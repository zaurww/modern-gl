"""Helpers shared by the write services (Ledger, Inventory)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr

MAX_SUBCONTO = 3

Subconto = tuple[int | None, int | None, int | None]


def now() -> str:
    """The current UTC time as stored in the database."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def pad_subconto(values: Sequence[int | None], line_no: int | None = None) -> Subconto:
    """Up to three subconto values, padded with None to exactly three."""
    if len(values) > MAX_SUBCONTO:
        if line_no is None:
            raise ValidationError(tr("больше {n} субконто", n=MAX_SUBCONTO))
        raise ValidationError(
            tr("строка {line}: больше {n} субконто", line=line_no, n=MAX_SUBCONTO)
        )
    first, second, third = [*values, *([None] * (MAX_SUBCONTO - len(values)))]
    return first, second, third


def company_row(conn: sqlite3.Connection, company_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if row is None:
        raise NotFoundError(tr("компания {id} не найдена", id=company_id))
    return row


def write_audit(
    conn: sqlite3.Connection,
    company_id: int | None,
    actor: str,
    entity: str,
    entity_id: int,
    action: str,
    details: dict,
) -> None:
    """Append an event to the audit trail (it is never updated or deleted)."""
    conn.execute(
        "INSERT INTO audit_events (company_id, at, actor, entity, entity_id, action, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            company_id,
            now(),
            actor,
            entity,
            entity_id,
            action,
            json.dumps(details, ensure_ascii=False),
        ),
    )
