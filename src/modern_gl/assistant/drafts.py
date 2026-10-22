"""Drafts the assistant prepares for a person to post (D84).

The assistant only ever writes drafts of journal documents, through `Ledger` — the same
checks as typing them in. It never posts, and changes or deletes only drafts it entered
itself: the audit trail names it as the author («AI · Claude»), which the document's head
shows (D82). Names, not ids, come from the model: accounts by code, directory elements by
name or VÖEN; an element missing from a directory is an error — the person adds it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from modern_gl.application.authorship import document_authors
from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import document_by_number, load_document
from modern_gl.assistant import answers
from modern_gl.assistant.companies import Companies
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

AI = "AI · "  # an actor starting so is the assistant
LINE_KEYS = {
    "debit",
    "debit_subconto",
    "credit",
    "credit_subconto",
    "amount",
    "memo",
    "e_qaime",
    "currency",
    "currency_amount",
}


@dataclass
class Drafts:
    companies: Companies
    client: Callable[[], str]  # the client's name, known after initialize

    @property
    def actor(self) -> str:
        return AI + (self.client() or "MCP")

    def create(self, date: str, memo: str, postings: list[dict], company: str = "") -> dict:
        with self._writing(company) as (ledger, company_id):
            lines = _lines(Catalog(ledger.conn, company_id), postings)
            doc_id = ledger.create_draft(company_id, date, lines, memo)
            return _answer(ledger, company_id, doc_id)

    def update(
        self, number: int, date: str, memo: str, postings: list[dict], company: str = ""
    ) -> dict:
        with self._writing(company) as (ledger, company_id):
            doc_id = self._own_draft(ledger.conn, company_id, number)
            lines = _lines(Catalog(ledger.conn, company_id), postings)
            ledger.update_draft(company_id, doc_id, date, lines, memo)
            return _answer(ledger, company_id, doc_id)

    def delete(self, number: int, company: str = "") -> dict:
        with self._writing(company) as (ledger, company_id):
            ledger.delete_draft(company_id, self._own_draft(ledger.conn, company_id, number))
            return {"deleted": number}

    @contextmanager
    def _writing(self, company: str) -> Iterator[tuple[Ledger, int]]:
        """The company file itself, briefly: the program may have it open — SQLite lets
        both write in turn; a file behind the program's schema is backed up first."""
        conn, company_id = self.companies.workspace.open(self.companies.path(company))
        try:
            yield Ledger(conn, actor=self.actor), company_id
        finally:
            conn.close()

    def _own_draft(self, conn: Connection, company_id: int, number: int) -> int:
        doc_id = document_by_number(conn, company_id, number)
        authors = document_authors(conn, company_id, doc_id)
        if authors is None or not authors.entered_by.startswith(AI):
            raise ValueError(tr("документ №{n} ввёл не помощник — его меняет человек", n=number))
        return doc_id


def _answer(ledger: Ledger, company_id: int, doc_id: int) -> dict:
    number = load_document(ledger.conn, company_id, doc_id).number
    problem = ledger.posting_problem(company_id, doc_id)
    return {
        **answers.document(ledger.conn, company_id, number),
        "would_post": problem is None,
        **({"problem": problem} if problem else {}),
        "note": "a draft: the user checks and posts it in the program",
    }


def _lines(cat: Catalog, postings: list[dict]) -> list[PostingInput]:
    if not postings:
        raise ValueError(tr("нет проводок"))
    return [_line(cat, i, p) for i, p in enumerate(postings, start=1)]


def _line(cat: Catalog, i: int, p: dict) -> PostingInput:
    unknown = set(p) - LINE_KEYS
    if unknown:
        raise ValueError(tr("строка {line}: лишние поля {keys}", line=i, keys=sorted(unknown)))
    debit = cat.resolve_account(str(p.get("debit", "")))
    credit = cat.resolve_account(str(p.get("credit", "")))
    currency = cat.resolve_currency(p["currency"]).id if p.get("currency") else None
    return PostingInput(
        debit.id,
        credit.id,
        _amount(i, p.get("amount")),
        _subconto(cat, debit, p.get("debit_subconto") or []),
        _subconto(cat, credit, p.get("credit_subconto") or []),
        str(p.get("memo") or ""),
        currency,
        _amount(i, p["currency_amount"]) if p.get("currency_amount") is not None else None,
        str(p.get("e_qaime") or ""),
    )


def _amount(line: int, value: object) -> str:
    """An amount as text ("261.13"): a JSON number would arrive as a float."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(tr('строка {line}: сумма — строкой, например "261.13"', line=line))
    return str(value)


def _subconto(cat: Catalog, account: AccountInfo, names: list[str]) -> list[int | None]:
    """The elements by name (or VÖEN) in the order of the account's subconto; a contract is
    looked for among its counterparty's."""
    kinds = [k for k in account.sc_kinds if k is not None]
    if len(names) > len(kinds):
        raise ValueError(
            tr(
                "у счёта {code} субконто: {kinds}",
                code=account.short,
                kinds=", ".join(cat.kinds[k] for k in kinds) or "—",
            )
        )
    values: list[int | None] = []
    for pos, name in enumerate(names):
        kind = account.sc_kinds[pos]
        if not name or kind is None:
            values.append(None)
            continue
        slot = cat.owner_slot(account, pos)
        owner = values[slot] if slot is not None and slot < len(values) else None
        found = cat.resolve_value(kind, str(name), owner)
        if found is None:
            raise LookupError(
                tr(
                    "«{name}» нет в справочнике «{kind}» — его добавляет человек в программе",
                    name=name,
                    kind=cat.kinds[kind],
                )
            )
        values.append(found)
    return values
