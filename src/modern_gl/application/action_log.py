"""«Журнал действий» of a company (D178): who did what, when and why — read
from the audit trail (D82, D96), with the sessions (the company opened and closed, on
which computer). Nothing new is stored but the sessions (`Ledger.log_session`).

Each event says what was done (a noun: «Проведение», «Удаление» — the same for every kind
of object) and to what: the kind and what tells it apart — a number, a code, a name; one
deleted since — from what its event kept. A document, a module's document — what opens."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from modern_gl.application.history import reason_of
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import N_
from modern_gl.infrastructure.db import Connection, Row

LIMIT = 2000  # newest events shown; a narrower period or a name finds older ones
SESSION = "session"

# audit entity -> what the user reads (Russian, for tr())
OBJECTS: dict[str, str] = {
    "document": N_("Документ"),
    "bank_operation": N_("Банковская операция"),
    "bank_statement": N_("Выписка банка"),
    "bank_account": N_("Банковский счёт"),
    "conversion": N_("Конвертация"),
    "inventory_document": N_("Складской документ"),
    "inventory_item": N_("Товар"),
    "inventory_unit": N_("Единица измерения"),
    "warehouse": N_("Склад"),
    "landed_cost_type": N_("Вид доп. расходов"),
    "account": N_("Счёт"),
    "account_role": N_("Роль счёта"),
    "inventory_sale_account": N_("Счета продажи"),
    "currency": N_("Валюта"),
    "subconto_kind": N_("Справочник"),
    "subconto_value": N_("Элемент справочника"),
    "tag": N_("Метка"),
    "entry_template": N_("Шаблон"),
    "company": N_("Компания"),
    SESSION: N_("Компания"),
}

# audit action -> what was done, a noun (Russian, for tr())
ACTIONS: dict[str, str] = {
    "open": N_("Открытие"),
    "close": N_("Закрытие"),
    "create": N_("Создание"),
    "create_draft": N_("Черновик"),
    "update_draft": N_("Правка черновика"),
    "update": N_("Изменение"),
    "post": N_("Проведение"),
    "repost": N_("Исправление проведённого"),
    "reverse": N_("Сторно"),
    "unpost": N_("Отмена проведения"),
    "delete": N_("Удаление"),
    "rename": N_("Новое название"),
    "show": N_("Возврат из скрытых"),
    "hide": N_("Скрытие"),
    "set": N_("Назначение"),
    "clear": N_("Снятие"),
    "move": N_("Перенос в другую группу"),
    "set_rate": N_("Курс"),
    "delete_rate": N_("Удаление курса"),
    "set_type": N_("Тип счёта"),
    "set_class": N_("Класс счёта"),
    "set_tax": "VÖEN",
    "set_tax_id": "VÖEN",
    "legal_name": N_("Полное название"),
    "set_currency": N_("Валюта"),
    "set_owner": N_("Владелец"),
    "set_tags": N_("Метки"),
    "set_minimum": N_("Минимальный остаток"),
    "set_closed_through": N_("Закрытый период"),
    "set_document_language": N_("Язык документов"),
    "set_mode": N_("Режим компании"),
    "set_parallel_books": N_("Параллельные книги"),
    "set_vat_payer_from": N_("Плательщик ƏDV с"),
    "attach_invoice": "E-qaimə",
    "fill_expense_account": N_("Счёт расходов"),
    "fill_sale_subconto": N_("Субконто продажи"),
}

# entity -> SQL of (id, label) for the ids asked; ? — the company, then the ids
_LABELS: dict[str, str] = {
    "document": "SELECT id, '№' || number FROM documents WHERE company_id = ? AND id IN ({ids})",
    "bank_operation": (
        "SELECT o.id, '№' || d.number FROM bank_operations o JOIN documents d "
        "ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ? AND o.id IN ({ids})"
    ),
    "conversion": (
        "SELECT c.id, '№' || d.number FROM currency_conversions c JOIN documents d "
        "ON d.company_id = c.company_id AND d.id = c.document_id "
        "WHERE c.company_id = ? AND c.id IN ({ids})"
    ),
    "inventory_document": (
        "SELECT id, '№' || number FROM inventory_documents WHERE company_id = ? AND id IN ({ids})"
    ),
    "inventory_item": (
        "SELECT i.id, v.name FROM inventory_items i JOIN subconto_values v "
        "ON v.company_id = i.company_id AND v.id = i.subconto_value_id "
        "WHERE i.company_id = ? AND i.id IN ({ids})"
    ),
    "warehouse": (
        "SELECT w.id, v.name FROM warehouses w JOIN subconto_values v "
        "ON v.company_id = w.company_id AND v.id = w.subconto_value_id "
        "WHERE w.company_id = ? AND w.id IN ({ids})"
    ),
    "account": "SELECT id, code FROM accounts WHERE company_id = ? AND id IN ({ids})",
    "account_role": "SELECT id, code FROM accounts WHERE company_id = ? AND id IN ({ids})",
    "inventory_sale_account": (
        "SELECT id, code FROM accounts WHERE company_id = ? AND id IN ({ids})"
    ),
    "currency": "SELECT id, code FROM currencies WHERE company_id = ? AND id IN ({ids})",
    "bank_account": "SELECT id, name FROM subconto_values WHERE company_id = ? AND id IN ({ids})",
    **{
        entity: "SELECT id, name FROM companies WHERE id = ? AND id IN ({ids})"
        for entity in ("company", SESSION)
    },
    **{
        entity: f"SELECT id, name FROM {table} WHERE company_id = ? AND id IN ({{ids}})"
        for entity, table in (
            ("subconto_kind", "subconto_kinds"),
            ("subconto_value", "subconto_values"),
            ("tag", "tags"),
            ("entry_template", "entry_templates"),
            ("landed_cost_type", "landed_cost_types"),
            ("inventory_unit", "inventory_units"),
        )
    },
}

# entity -> SQL of (id, the GL document that opens it) for the ids asked
_OPENS: dict[str, str] = {
    "document": "SELECT id, id FROM documents WHERE company_id = ? AND id IN ({ids})",
    "bank_operation": (
        "SELECT id, document_id FROM bank_operations WHERE company_id = ? AND id IN ({ids})"
    ),
    "conversion": (
        "SELECT id, document_id FROM currency_conversions WHERE company_id = ? AND id IN ({ids})"
    ),
    "inventory_document": (
        "SELECT id, gl_document_id FROM inventory_documents WHERE company_id = ? AND id IN ({ids})"
    ),
}
# what an event of a deleted object kept of it, by entity: the key of its details
_KEPT = {"document": "number", "account": "code", "currency": "code"}


@dataclass(frozen=True)
class LogFilter:
    company_id: int
    date_from: date | str  # the user's days, not UTC
    date_to: date | str
    actor: str = ""  # "" — everybody


@dataclass(frozen=True)
class LogEvent:
    at: str  # UTC, ISO, as in audit_events
    actor: str
    action: str  # Russian, for tr() — or the code of an action not known here
    kind: str  # Russian, for tr() — the kind of object (or its code)
    subject: str  # what tells the object apart: «№12», «60», a name; "" — none
    reason: str
    computer: str  # a session's: the computer and its user («OFFICE-PC · aynur»)
    document_id: int | None  # the GL document that opens it; None — nothing to open
    entity: str = ""  # the audit entity («document», «inventory_document»…)


def action_log(conn: Connection, flt: LogFilter, limit: int = LIMIT) -> list[LogEvent]:
    """The company's events of the period, newest first, at most `limit`."""
    start, end = _utc_bounds(flt.date_from, flt.date_to)
    sql = (
        "SELECT entity, entity_id, at, actor, action, details FROM audit_events "
        "WHERE company_id = ? AND at >= ? AND at < ?"
    )
    params: list[object] = [flt.company_id, start, end]
    if flt.actor:
        sql += " AND actor = ?"
        params.append(flt.actor)
    rows = conn.execute(sql + " ORDER BY at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
    events: list[tuple[str, int | None, Row]] = [
        (str(r["entity"]), r["entity_id"], r) for r in rows
    ]
    labels = {k: str(v) for k, v in _lookup(conn, flt.company_id, _LABELS, events).items()}
    labels |= _kept_labels(conn, flt.company_id, events, labels)
    opens = {k: int(str(v)) for k, v in _lookup(conn, flt.company_id, _OPENS, events).items()}
    return [_event(entity, entity_id, r, labels, opens) for entity, entity_id, r in events]


def log_actors(conn: Connection, company_id: int) -> list[str]:
    """Everybody the company's audit trail names, in alphabetical order."""
    rows = conn.execute(
        "SELECT DISTINCT actor FROM audit_events WHERE company_id = ? ORDER BY actor",
        (company_id,),
    )
    return [str(r["actor"]) for r in rows]


def _event(
    entity: str,
    entity_id: int | None,
    row: Row,
    labels: dict[tuple[str, int], str],
    opens: dict[tuple[str, int], int],
) -> LogEvent:
    details = _details(row["details"])
    key = (entity, entity_id or 0)
    subject = labels.get(key, "")
    computer = ""
    if entity == SESSION:
        computer = " · ".join(str(details[k]) for k in ("machine", "user") if details.get(k))
    return LogEvent(
        str(row["at"]),
        str(row["actor"]),
        ACTIONS.get(str(row["action"]), str(row["action"])),
        OBJECTS.get(entity, entity),
        subject,
        reason_of(row["details"]),
        computer,
        opens.get(key),
        entity,
    )


def _lookup(
    conn: Connection,
    company_id: int,
    queries: dict[str, str],
    events: Iterable[tuple[str, int | None, Row]],
) -> dict[tuple[str, int], object]:
    """(entity, id) -> what the query of the entity gives, for the ids of the events."""
    wanted: dict[str, set[int]] = {}
    for entity, entity_id, _ in events:
        if entity in queries and entity_id:
            wanted.setdefault(entity, set()).add(int(entity_id))
    found: dict[tuple[str, int], object] = {}
    for entity, ids in wanted.items():
        for chunk in _chunks(sorted(ids)):
            sql = queries[entity].format(ids=", ".join("?" * len(chunk)))
            for r in conn.execute(sql, (company_id, *chunk)):
                if r[1] is not None:
                    found[(entity, int(r[0]))] = r[1]
    return found


def _chunks(ids: Sequence[int], size: int = 500) -> list[Sequence[int]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def _details(text: object) -> dict[str, object]:
    data = json.loads(str(text)) if text else {}
    return data if isinstance(data, dict) else {}


def _kept_labels(
    conn: Connection,
    company_id: int,
    events: Iterable[tuple[str, int | None, Row]],
    labels: dict[tuple[str, int], str],
) -> dict[tuple[str, int], str]:
    """Objects deleted since: their number, code or name from what any of their events
    kept (an unposting, a deletion keep the whole document)."""
    gone: dict[str, set[int]] = {}
    for entity, entity_id, _ in events:
        if entity_id and (entity, entity_id) not in labels:
            gone.setdefault(entity, set()).add(int(entity_id))
    found: dict[tuple[str, int], str] = {}
    for entity, ids in gone.items():
        field = _KEPT.get(entity, "name")
        for chunk in _chunks(sorted(ids)):
            rows = conn.execute(
                "SELECT entity_id, details FROM audit_events WHERE company_id = ? "
                f"AND entity = ? AND entity_id IN ({', '.join('?' * len(chunk))}) ORDER BY id",
                (company_id, entity, *chunk),
            )
            for r in rows:
                value = _details(r["details"]).get(field)
                if value not in (None, ""):
                    text = f"№{value}" if entity == "document" else str(value)
                    found.setdefault((entity, int(r["entity_id"])), text)
    return found


def _utc_bounds(date_from: date | str, date_to: date | str) -> tuple[str, str]:
    """The user's days from–to as UTC times [start, end): stored times are UTC."""
    first = date.fromisoformat(iso_date(date_from))
    last = date.fromisoformat(iso_date(date_to)) + timedelta(days=1)

    def utc(day: date) -> str:
        local = datetime.combine(day, time()).astimezone()  # the computer's midnight
        return local.astimezone(UTC).isoformat(timespec="seconds")

    return utc(first), utc(last)
