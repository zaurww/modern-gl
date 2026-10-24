"""Helpers shared by the write services (Ledger, Inventory)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure import db
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.infrastructure.db import insert as insert  # used by the write services

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


def closed_on(company: Row, day: str) -> bool:
    """Whether a day (ISO) is in the company's closed period: on `closed_through` or before."""
    closed = company["closed_through"]
    return closed is not None and day <= closed


def require_open(company: Row, day: str, explain: Callable[[str], str]) -> None:
    """Refuse a change dated `day` (ISO) in the company's closed period: PeriodClosedError
    with `explain(closed)` — the text, given the last closed day as the user reads it."""
    if closed_on(company, day):
        raise PeriodClosedError(explain(ru_date(company["closed_through"])))


def group_path(parent_id: int | None, node: Callable[[int], tuple[str, int | None] | None]) -> str:
    """The groups above a directory element, outermost first: «Avadanlıq / Kabellər».
    `node(id)` gives a group's (name, parent); a chain of parents that loops stops."""
    names: list[str] = []
    seen: set[int] = set()
    while parent_id is not None and parent_id not in seen and (found := node(parent_id)):
        seen.add(parent_id)
        names.append(found[0])
        parent_id = found[1]
    return " / ".join(reversed(names))


def with_reason(details: dict, reason: str) -> dict:
    """An audit event's details with why the change was made, when it was told."""
    reason = reason.strip()
    return {**details, "reason": reason} if reason else details


def company_row(conn: Connection, company_id: int) -> Row:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if row is None:
        raise NotFoundError(tr("компания {id} не найдена", id=company_id))
    return row


def write_audit(
    conn: Connection,
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


# columns that refer to a row without a foreign key (the expense subconto of a purchase line)
UNCHECKED_REFERENCES: dict[str, list[tuple[str, str]]] = {
    "subconto_values": [("inventory_lines", f"cost_sc{n}") for n in range(1, MAX_SUBCONTO + 1)],
}
# where a row is used, told by the table that refers to it ({n}: a document number)
USAGE_TEXTS: dict[str, str] = {
    "postings": "есть проводки в документе №{n}",
    "entry_template_lines": "он есть в шаблоне «{name}»",
    "inventory_lines": "он есть в складском документе №{n}",
    "inventory_items": "это товар склада или счёт запасов товара",
    "warehouses": "это склад",
    "stock_movements": "по нему есть движения на складе",
    "account_roles": "он выбран в настройках склада (роль счёта)",
    "bank_operations": "он есть в банковской операции",
    "bank_operation_lines": "он есть в банковской операции",
    "currency_conversions": "он есть в конвертации валюты",
    "conversion_fees": "он есть в конвертации валюты",
    "landed_cost_charges": "он есть в документе «Дополнительные расходы»",
}


def where_used(conn: Connection, company_id: int, table: str, row_id: int) -> str | None:
    """Why the row cannot be deleted: the first place that refers to it (postings first),
    or None when nothing does. The places are read from the foreign keys, so a new
    table that refers to accounts or directory elements is checked without changes here."""
    for referrer, columns in _references(conn, table):
        own = db.column_names(conn, referrer)
        where = " OR ".join(f'"{column}" = ?' for column in columns)
        params: list[object] = [row_id] * len(columns)
        if "company_id" in own:
            where = f"({where}) AND company_id = ?"
            params.append(company_id)
        order = "ORDER BY id " if "id" in own else ""  # the earliest document first
        found = conn.execute(
            f'SELECT * FROM "{referrer}" WHERE {where} {order}LIMIT 1', params
        ).fetchone()
        if found is not None:
            return _usage_text(conn, referrer, found)
    return None


def _references(conn: Connection, table: str) -> list[tuple[str, list[str]]]:
    """The tables that refer to the table, each with its columns that do."""
    found: dict[str, list[str]] = {}
    for referrer, column in UNCHECKED_REFERENCES.get(table, []):
        found.setdefault(referrer, []).append(column)
    for referrer in db.table_names(conn):
        for key in db.foreign_key_columns(conn, referrer):
            # a cascaded row is a part of the referred one (an element's tags), no use
            if key.table == table and key.to == "id" and key.on_delete != "CASCADE":
                found.setdefault(referrer, []).append(key.column)
    # the clearest reason first: a document by its number
    first = {"postings": 0, "inventory_lines": 1}
    return sorted(found.items(), key=lambda ref: first.get(ref[0], 2))


def _usage_text(conn: Connection, referrer: str, row: Row) -> str:
    if referrer == "accounts":  # its parent_id
        return tr("у счёта есть субсчета")
    if referrer == "subconto_values":  # its owner_id
        return tr("к нему относится «{name}»", name=row["name"])
    if referrer == "postings":
        doc = conn.execute("SELECT number FROM documents WHERE id = ?", (row["document_id"],))
        return tr(USAGE_TEXTS[referrer], n=doc.fetchone()["number"])
    if referrer == "inventory_lines":
        doc = conn.execute(
            "SELECT number FROM inventory_documents WHERE id = ?", (row["document_id"],)
        )
        return tr(USAGE_TEXTS[referrer], n=doc.fetchone()["number"])
    if referrer == "entry_template_lines":
        template = conn.execute(
            "SELECT name FROM entry_templates WHERE id = ?", (row["template_id"],)
        )
        return tr(USAGE_TEXTS[referrer], name=template.fetchone()["name"])
    if referrer in USAGE_TEXTS:
        return tr(USAGE_TEXTS[referrer])
    return tr("он используется ({table})", table=referrer)
