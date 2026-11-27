"""Two elements of the counterparties' directory that are one counterparty become one
(D232): everything that refers to the extra one — postings, the
modules' documents, contracts, templates — refers to the one that stays, and the extra
one goes. Amounts, accounts, numbers and dates do not change.

The places are read from the foreign keys (as `where_used` reads them), so a table added
later is taken along. A posted posting is immutable in the database: its document turns
a draft for the moment of the change and is posted back as it was, in one transaction.
A closed period is not touched — the merge is refused until the period is opened."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.common import references_to
from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import IntegrityError, Row, transaction

TABLE = "subconto_values"


@dataclass(frozen=True)
class MergePlan:
    """What a merge moves: for the person to see before it is done."""

    keep_name: str
    drop_name: str
    documents: int  # GL documents with a posting of the extra one (drafts too)
    contracts: int  # elements that belong to it
    takes_tax_id: str | None  # the VÖEN the one that stays gets from the extra one


class SubcontoMergeCommands(SubcontoCommands):
    """A counterparty entered twice: the plan of a merge and the merge; audited."""

    def counterparty_merge_plan(self, company_id: int, keep_id: int, drop_id: int) -> MergePlan:
        """What merging `drop_id` into `keep_id` will do; a ValidationError says why it
        cannot be done (not counterparties, two different VÖEN, a closed period)."""
        keep, drop = self._merge_pair(company_id, keep_id, drop_id)
        contracts = self.conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE company_id = ? AND owner_id = ?",
            (company_id, drop_id),
        ).fetchone()[0]
        takes = drop["tax_id"] if not keep["tax_id"] else None
        documents = len(self._documents_of(company_id, drop_id))
        return MergePlan(keep["name"], drop["name"], documents, contracts, takes)

    def merge_counterparties(self, company_id: int, keep_id: int, drop_id: int) -> MergePlan:
        """`drop_id` becomes `keep_id` everywhere and is removed — all or nothing. The one
        that stays takes the VÖEN, the country and the official name it lacks."""
        with transaction(self.conn):
            plan = self.counterparty_merge_plan(company_id, keep_id, drop_id)
            keep, drop = self._merge_pair(company_id, keep_id, drop_id)
            documents = self._documents_of(company_id, drop_id)
            try:
                self._move_references(company_id, keep_id, drop_id, documents)
                if not keep["tax_id"] and drop["tax_id"]:
                    foreign = bool(drop["nonresident"])
                    self.set_subconto_value_tax(
                        company_id, keep_id, drop["tax_id"], foreign, drop["country"]
                    )
                if not keep["legal_name"] and drop["legal_name"]:
                    self.set_subconto_value_legal_name(company_id, keep_id, drop["legal_name"])
                self.conn.execute(
                    f"DELETE FROM {TABLE} WHERE company_id = ? AND id = ?", (company_id, drop_id)
                )
            except IntegrityError as e:
                raise ValidationError(
                    tr("«{name}» не удалось объединить: {error}", name=drop["name"], error=e)
                ) from e
            details = {
                "from": {k: drop[k] for k in ("id", "name", "tax_id", "legal_name")},
                "documents": [d["number"] for d in documents],
            }
            self._audit(company_id, "subconto_value", keep_id, "merge", details)
        return plan

    def _merge_pair(self, company_id: int, keep_id: int, drop_id: int) -> tuple[Row, Row]:
        if keep_id == drop_id:
            raise ValidationError(tr("это один и тот же элемент"))
        keep = self._subconto_value(company_id, keep_id)
        drop = self._subconto_value(company_id, drop_id)
        kind = self.conn.execute(
            "SELECT code FROM subconto_kinds WHERE company_id = ? AND id = ?",
            (company_id, keep["kind_id"]),
        ).fetchone()
        if keep["kind_id"] != drop["kind_id"] or kind["code"] != "counterparty":
            raise ValidationError(tr("объединяются только контрагенты"))
        if keep["is_group"] or drop["is_group"]:
            raise ValidationError(tr("группу объединить нельзя"))
        if keep["tax_id"] and drop["tax_id"] and keep["tax_id"] != drop["tax_id"]:
            raise ValidationError(
                tr(
                    "у «{a}» и «{b}» разные VÖEN ({x} и {y}) — это два разных контрагента",
                    a=keep["name"],
                    b=drop["name"],
                    x=keep["tax_id"],
                    y=drop["tax_id"],
                )
            )
        closed = self._company(company_id)["closed_through"]
        late = [
            d
            for d in self._documents_of(company_id, drop_id)
            if d["posted_at"] and closed and d["doc_date"] <= closed
        ]
        if late:
            raise PeriodClosedError(
                tr(
                    "у «{name}» есть проведённые документы в закрытом периоде (по {day}): "
                    "{n}. Откройте период, объедините и закройте его снова.",
                    name=drop["name"],
                    day=ru_date(closed),
                    n=len(late),
                )
            )
        return keep, drop

    def _documents_of(self, company_id: int, value_id: int) -> list[Row]:
        """The GL documents with a posting of the element, drafts too."""
        return self.conn.execute(
            "SELECT d.id, d.number, d.doc_date, d.posted_at FROM documents d "
            "WHERE d.company_id = ? AND EXISTS (SELECT 1 FROM postings p "
            "WHERE p.company_id = d.company_id AND p.document_id = d.id AND ? IN "
            "(p.dt_sc1, p.dt_sc2, p.dt_sc3, p.ct_sc1, p.ct_sc2, p.ct_sc3)) ORDER BY d.id",
            (company_id, value_id),
        ).fetchall()

    def _move_references(
        self, company_id: int, keep_id: int, drop_id: int, documents: list[Row]
    ) -> None:
        """Every reference to the extra one goes to the one that stays; the posted
        documents are drafts while their postings change and posted again as they were."""
        posted = [d for d in documents if d["posted_at"]]
        for doc in posted:  # a posted posting changes only in a draft (the triggers)
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL "
                "WHERE company_id = ? AND id = ?",
                (company_id, doc["id"]),
            )
        for ref in references_to(self.conn, TABLE):
            for column in dict.fromkeys(ref.columns):
                where = f'"{column}" = ?' + (" AND company_id = ?" if ref.by_company else "")
                params = (keep_id, drop_id, company_id) if ref.by_company else (keep_id, drop_id)
                self.conn.execute(f'UPDATE "{ref.table}" SET "{column}" = ? WHERE {where}', params)
        for doc in posted:
            self.conn.execute(
                "UPDATE documents SET status = 'posted', posted_at = ? "
                "WHERE company_id = ? AND id = ?",
                (doc["posted_at"], company_id, doc["id"]),
            )
