"""A line of a file the books hold already, typed by hand (D-new): a bank operation
without a statement reference on the same bank account, day, direction and amount gets
the file's reference instead of a second operation — hand-typed and loaded lines mix
without doubling. Several hand-typed lines of that amount on the day and not as many
lines in the file: which one is which nobody knows — the file's lines wait as drafts that
say so, and the statement shows them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.bank.file_conversions import FileConversionCommands
from modern_gl.application.bank.file_import import CONVERSION, FileOperation
from modern_gl.application.bank.imported import LINKED, ImportRow
from modern_gl.i18n import tr

# (the GL account, the element of its directory, the day, the direction, the amount)
LinkKey = tuple[int, int | None, str, str, int]


def link_key(op: FileOperation) -> LinkKey:
    return (op.place.account_id, op.place.value_id, op.day, op.direction, op.amount)


@dataclass
class HandLinks:
    """The hand-typed operations of the days of a file, by `link_key`, as (id, number) in
    the order of their numbers; `linkable` — the keys whose count is the file's."""

    typed: dict[LinkKey, list[tuple[int, int]]] = field(default_factory=dict)
    linkable: set[LinkKey] = field(default_factory=set)

    def to_import(self, ops: Sequence[FileOperation]) -> list[FileOperation]:
        """The lines that become operations: the ones linked bring no counterparty."""
        return [op for op in ops if op.kind == CONVERSION or link_key(op) not in self.linkable]


class FileLinkCommands(FileConversionCommands):
    def _hand_links(self, company_id: int, ops: Sequence[FileOperation]) -> HandLinks:
        lines = [op for op in ops if op.kind != CONVERSION]
        days = sorted({op.day for op in lines})
        if not days:
            return HandLinks()
        marks = ", ".join("?" * len(days))
        rows = self.conn.execute(
            "SELECT o.id, d.number, d.doc_date, o.direction, o.account_id, o.sc1, o.sc2, "
            "o.sc3, COALESCE((SELECT SUM(l.amount) FROM bank_operation_lines l "
            "WHERE l.company_id = o.company_id AND l.operation_id = o.id), 0) AS amount "
            "FROM bank_operations o "
            "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
            f"WHERE o.company_id = ? AND o.reference = '' AND d.doc_date IN ({marks}) "
            "ORDER BY d.number",
            (company_id, *days),
        ).fetchall()
        places = {(op.place.account_id, op.place.value_id) for op in lines}
        links = HandLinks()
        for r in rows:
            for account_id, value_id in places:
                if r["account_id"] != account_id:
                    continue
                if value_id is not None and value_id not in (r["sc1"], r["sc2"], r["sc3"]):
                    continue
                key = (account_id, value_id, r["doc_date"], r["direction"], r["amount"])
                links.typed.setdefault(key, []).append((r["id"], r["number"]))
        wanted = Counter(link_key(op) for op in lines)
        links.linkable = {key for key, typed in links.typed.items() if len(typed) == wanted[key]}
        return links

    def _link_hand_typed(
        self, company_id: int, op: FileOperation, links: HandLinks
    ) -> tuple[ImportRow | None, str]:
        """The line linked to the hand-typed operation (it gets the reference; the audit
        trail keeps that it had none), or why the line must wait ("" — load it)."""
        key = link_key(op)
        typed = links.typed.get(key)
        if not typed:
            return None, ""
        if key not in links.linkable:
            return None, tr(
                "за этот день введено вручную строк на эту сумму: {n} — проверьте дубли",
                n=len(typed),
            )
        operation_id, _ = typed.pop(0)
        self.conn.execute(
            "UPDATE bank_operations SET reference = ? WHERE company_id = ? AND id = ?",
            (op.reference, company_id, operation_id),
        )
        self._audit(company_id, "bank_operation", operation_id, "update", {"reference": ""})
        document = self._bank_row(company_id, operation_id)["document_id"]
        return ImportRow(op, LINKED, document_id=document), ""
