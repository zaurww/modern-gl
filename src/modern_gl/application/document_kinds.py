"""One document in the user's eyes (D213): every document is named by
its kind and the number the user knows — «Alış №6», «Bank məxarici №13», «Əməliyyat №14».

A GL document a module made is named by the module's document (`document_owners`,
`owner_kind`, `owner_number`); the core never reads the modules' tables. The GL number
stays the journal's inner order and the key of a document; the user sees the name."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from modern_gl.application.common import batches
from modern_gl.i18n import N_, fold, tr
from modern_gl.infrastructure.db import Connection

JOURNAL = "journal"  # a document entered in the journal by hand
OPENING_BALANCES = "opening_balances"  # the core's opening balances (D39, D40)

# the kind of a document, as the user calls it; the inventory's doc_type keeps its word
KIND_NAMES = {
    JOURNAL: N_("Операция"),
    OPENING_BALANCES: N_("Начальные остатки"),
    "opening": N_("Начальные остатки"),
    "receipt": N_("Покупка"),
    "incoming": N_("Оприходование"),
    "issue": N_("Списание"),
    "sale": N_("Продажа"),
    "transfer": N_("Перемещение"),
    "landed_cost": N_("Дополнительные расходы"),
    "purchase_return": N_("Возврат поставщику"),
    "sale_return": N_("Возврат от покупателя"),
    "conversion": N_("Конвертация"),
    "bank_in": N_("Банк, приход"),
    "bank_out": N_("Банк, расход"),
    "cash_in": N_("Приходный кассовый ордер"),
    "cash_out": N_("Расходный кассовый ордер"),
}

# what a query joins to name its documents `d` (the aliases `own` and `ob` are taken)
NAME_JOINS = """
    LEFT JOIN document_owners own
        ON own.company_id = d.company_id AND own.document_id = d.id AND own.role = 'made'
    LEFT JOIN opening_balance_documents ob
        ON ob.company_id = d.company_id AND ob.document_id = d.id"""
# the kind and the number the user knows, over NAME_JOINS
KIND_SQL = (
    f"COALESCE(own.owner_kind, CASE WHEN ob.document_id IS NOT NULL "
    f"THEN '{OPENING_BALANCES}' ELSE '{JOURNAL}' END)"
)
NUMBER_SQL = "COALESCE(own.owner_number, d.number)"


def kind_name(kind: str) -> str:
    """«Покупка», «Операция»… in the interface's language."""
    return tr(KIND_NAMES.get(kind, KIND_NAMES[JOURNAL]))


def document_title(kind: str, number: int) -> str:
    """«Покупка №6»."""
    return tr("{kind} №{n}", kind=kind_name(kind), n=number)


def kinds_named(text: str) -> list[str]:
    """The kinds whose name holds the folded `text` — what a search by «alış» finds."""
    return [kind for kind in KIND_NAMES if text in fold(kind_name(kind))]


@dataclass(frozen=True)
class DocumentName:
    """What a document is called: its kind and the number the user knows."""

    kind: str
    number: int

    @property
    def kind_text(self) -> str:
        return kind_name(self.kind)

    @property
    def title(self) -> str:
        return document_title(self.kind, self.number)


class _Titled(Protocol):
    documents: list[tuple[int, int]]  # (GL id, GL number)
    titles: dict[int, str]


def name_rows(conn: Connection, company_id: int, rows: Iterable[_Titled]) -> None:
    """Each row's documents named as the user knows them (`titles`, by GL id), read at
    once — for a page that shows them, not for the reckoning that gathers them."""
    rows = list(rows)
    names = document_names(conn, company_id, (i for r in rows for i, _ in r.documents))
    for r in rows:
        r.titles = {i: names[i].title for i, _ in r.documents if i in names}


def document_names(
    conn: Connection, company_id: int, doc_ids: Iterable[int]
) -> dict[int, DocumentName]:
    """The names of these GL documents, read at once (not one by one)."""
    names: dict[int, DocumentName] = {}
    for part in batches(sorted(set(doc_ids))):
        marks = ", ".join("?" * len(part))
        for row in conn.execute(
            f"""
            SELECT d.id, {KIND_SQL} AS kind, {NUMBER_SQL} AS number
            FROM documents d {NAME_JOINS}
            WHERE d.company_id = ? AND d.id IN ({marks})
            ORDER BY d.id, own.owner_number, own.owner_id
            """,
            (company_id, *part),
        ):
            names.setdefault(row["id"], DocumentName(row["kind"], row["number"]))
    return names
