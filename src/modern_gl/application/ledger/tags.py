"""Tags of directory elements (D64): «Связанная сторона», «Арендодатель» — for reports
by a property of the element, not by a subaccount."""

from __future__ import annotations

from collections.abc import Iterable

from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Row, insert, transaction


class TagCommands(LedgerBase):
    """Use cases of tags and the tags of an element; audited."""

    def add_tag(self, company_id: int, name: str) -> int:
        """A tag of the company: «Связанная сторона», «Арендодатель»."""
        name = " ".join(name.split())
        with transaction(self.conn):
            self._company(company_id)
            self._check_tag_name(company_id, name)
            tag_id = insert(
                self.conn, "INSERT INTO tags (company_id, name) VALUES (?, ?)", (company_id, name)
            )
            self._audit(company_id, "tag", tag_id, "create", {"name": name})
        return tag_id

    def rename_tag(self, company_id: int, tag_id: int, name: str) -> None:
        """Rename a tag (spaces collapsed); ValidationError if another tag has the name. Audited."""
        name = " ".join(name.split())
        with transaction(self.conn):
            old = self._tag(company_id, tag_id)
            if old["name"] == name:
                return
            self._check_tag_name(company_id, name, tag_id)
            self.conn.execute(
                "UPDATE tags SET name = ? WHERE company_id = ? AND id = ?",
                (name, company_id, tag_id),
            )
            self._audit(company_id, "tag", tag_id, "rename", {"from": old["name"], "to": name})

    def delete_tag(self, company_id: int, tag_id: int) -> None:
        """A tag says nothing to postings: it goes, and comes off every element."""
        with transaction(self.conn):
            old = self._tag(company_id, tag_id)
            values = [
                r["value_id"]
                for r in self.conn.execute(
                    "SELECT value_id FROM subconto_value_tags WHERE company_id = ? AND tag_id = ?",
                    (company_id, tag_id),
                )
            ]
            self.conn.execute(
                "DELETE FROM tags WHERE company_id = ? AND id = ?",
                (
                    company_id,
                    tag_id,
                ),
            )
            self._audit(
                company_id, "tag", tag_id, "delete", {"name": old["name"], "values": values}
            )

    def set_subconto_value_tags(
        self, company_id: int, value_id: int, tag_ids: Iterable[int]
    ) -> None:
        """The tags an element has, all at once (a group has none: it is not posted)."""
        wanted = set(tag_ids)
        with transaction(self.conn):
            value = self._subconto_value(company_id, value_id)
            if value["is_group"] and wanted:
                raise ValidationError(tr("у группы не бывает тегов — только у элементов"))
            for tag_id in wanted:
                self._tag(company_id, tag_id)
            old = {
                r["tag_id"]
                for r in self.conn.execute(
                    "SELECT tag_id FROM subconto_value_tags WHERE company_id = ? AND value_id = ?",
                    (company_id, value_id),
                )
            }
            if old == wanted:
                return
            self.conn.executemany(
                "DELETE FROM subconto_value_tags "
                "WHERE company_id = ? AND value_id = ? AND tag_id = ?",
                [(company_id, value_id, t) for t in old - wanted],
            )
            self.conn.executemany(
                "INSERT INTO subconto_value_tags (company_id, value_id, tag_id) VALUES (?, ?, ?)",
                [(company_id, value_id, t) for t in wanted - old],
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "set_tags",
                {"from": sorted(old), "to": sorted(wanted)},
            )

    def _tag(self, company_id: int, tag_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM tags WHERE company_id = ? AND id = ?", (company_id, tag_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("тег не найден"))
        return row

    def _check_tag_name(self, company_id: int, name: str, tag_id: int | None = None) -> None:
        """Not empty, and not another tag's name (any case, İ and i alike)."""
        if not name:
            raise ValidationError(tr("название не может быть пустым"))
        for r in self.conn.execute("SELECT id, name FROM tags WHERE company_id = ?", (company_id,)):
            if r["id"] != tag_id and fold(r["name"]) == fold(name):
                raise ValidationError(tr("тег «{name}» уже есть", name=r["name"]))
