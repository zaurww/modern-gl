"""Helpers shared by the write services (Ledger, Inventory)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure import db
from modern_gl.infrastructure.db import Connection, Row

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


def account_kinds(account: Row) -> Subconto:
    """The kinds of directory at the three subconto positions of an account (None: the
    position is not used); a row with `sc1_kind_id`, `sc2_kind_id`, `sc3_kind_id`."""
    return account["sc1_kind_id"], account["sc2_kind_id"], account["sc3_kind_id"]


def fill_subconto(
    account: Row, by_kind: Mapping[int, int | None], keep: Sequence[int | None] = ()
) -> Subconto:
    """The account's subconto filled by kind — the one rule for every module (a payment's
    counterparty on 60, the advance's contract on 62.2, the VAT account's supplier): at
    each position, the element `keep` has there (typed by hand), else the element of
    that position's kind in `by_kind` (kind id -> element id), else none."""
    kept = pad_subconto(keep)
    first, second, third = (
        value if value is not None else (None if kind is None else by_kind.get(kind))
        for kind, value in zip(account_kinds(account), kept, strict=True)
    )
    return first, second, third


# ids in one `IN (...)` of a query: well below the engine's limit of parameters
BATCH = 500


def batches[T](items: Sequence[T], size: int = BATCH) -> list[Sequence[T]]:
    """`items` in parts of at most `size`, in their order: a list read by `IN (...)`."""
    return [items[i : i + size] for i in range(0, len(items), size)]


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
    "postings": N_("есть проводки в документе №{n}"),
    "entry_template_lines": N_("он есть в шаблоне «{name}»"),
    "inventory_lines": N_("он есть в складском документе №{n}"),
    "inventory_items": N_("это товар склада или счёт запасов товара"),
    "warehouses": N_("это склад"),
    "stock_movements": N_("по нему есть движения на складе"),
    "account_roles": N_("он выбран в настройках склада (роль счёта)"),
    "bank_operations": N_("он есть в банковской операции"),
    "bank_operation_lines": N_("он есть в банковской операции"),
    "currency_conversions": N_("он есть в конвертации валюты"),
    "conversion_fees": N_("он есть в конвертации валюты"),
    "landed_cost_charges": N_("он есть в документе «Дополнительные расходы»"),
}


def where_used(conn: Connection, company_id: int, table: str, row_id: int) -> str | None:
    """Why the row cannot be deleted: the first place that refers to it (postings first),
    or None when nothing does. The places are read from the foreign keys, so a new
    table that refers to accounts or directory elements is checked without changes here."""
    for ref in _references(conn, table):
        where = " OR ".join(f'"{column}" = ?' for column in ref.columns)
        params: list[object] = [row_id] * len(ref.columns)
        if ref.by_company:
            where = f"({where}) AND company_id = ?"
            params.append(company_id)
        order = "ORDER BY id " if ref.has_id else ""  # the earliest document first
        found = conn.execute(
            f'SELECT * FROM "{ref.table}" WHERE {where} {order}LIMIT 1', params
        ).fetchone()
        if found is not None:
            return _usage_text(conn, ref.table, found)
    return None


@dataclass(frozen=True)
class Reference:
    """A table that refers to another, by these columns."""

    table: str
    columns: tuple[str, ...]
    by_company: bool  # it has company_id: a row is looked for in the company only
    has_id: bool  # it has an id to order by


# the references of a schema (a table -> the tables that refer to it), read once per
# process: the schema is the same in every connection of a version (migrations are
# frozen, D148), and a connection cannot keep it
_REFERENCES: dict[int, dict[str, tuple[Reference, ...]]] = {}


def _references(conn: Connection, table: str) -> tuple[Reference, ...]:
    """The tables that refer to the table, each with its columns that do."""
    version = db.schema_version(conn)
    schema = _REFERENCES.get(version)
    if schema is None:
        schema = _REFERENCES[version] = _read_references(conn)
    return schema.get(table, ())


def _read_references(conn: Connection) -> dict[str, tuple[Reference, ...]]:
    found: dict[str, dict[str, list[str]]] = {}  # table -> referrer -> columns
    for table, unchecked in UNCHECKED_REFERENCES.items():
        for referrer, column in unchecked:
            found.setdefault(table, {}).setdefault(referrer, []).append(column)
    for referrer in db.table_names(conn):
        for key in db.foreign_key_columns(conn, referrer):
            # a cascaded row is a part of the referred one (an element's tags), no use
            if key.to == "id" and key.on_delete != "CASCADE":
                found.setdefault(key.table, {}).setdefault(referrer, []).append(key.column)
    # the clearest reason first: a document by its number
    first = {"postings": 0, "inventory_lines": 1}
    columns = {table: db.column_names(conn, table) for table in db.table_names(conn)}
    return {
        table: tuple(
            Reference(referrer, tuple(cols), "company_id" in own, "id" in own)
            for referrer, cols in sorted(referrers.items(), key=lambda ref: first.get(ref[0], 2))
            if (own := columns.get(referrer, set())) is not None
        )
        for table, referrers in found.items()
    }


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
