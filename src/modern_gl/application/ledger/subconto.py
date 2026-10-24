"""Subconto kinds (directories) and their values."""

from __future__ import annotations

from collections.abc import Iterable

from modern_gl.application.common import insert, where_used
from modern_gl.application.ledger.base import LedgerBase, account_label
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.domain.tax_id import resident_tax_id
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import IntegrityError, Row, transaction


class SubcontoCommands(LedgerBase):
    def add_subconto_kind(
        self, company_id: int, code: str | None, name: str, owner_kind_id: int | None = None
    ) -> int:
        """Add a directory. Without a code (user-made directories) one is generated.
        With `owner_kind_id` its elements belong to elements of that directory, like
        contracts to counterparties (a 1C "подчинённый справочник")."""
        with transaction(self.conn):
            if code is None:
                taken = {
                    r["code"]
                    for r in self.conn.execute(
                        "SELECT code FROM subconto_kinds WHERE company_id = ?", (company_id,)
                    )
                }
                n = 1
                while f"custom_{n}" in taken:
                    n += 1
                code = f"custom_{n}"
            kind_id = insert(
                self.conn,
                "INSERT INTO subconto_kinds (company_id, code, name, owner_kind_id) "
                "VALUES (?, ?, ?, ?)",
                (company_id, code, name, owner_kind_id),
            )
            self._audit(company_id, "subconto_kind", kind_id, "create", {"code": code})
        return kind_id

    def subconto_kind_id(self, company_id: int, code: str) -> int:
        return self._kind_id(company_id, code)

    def add_subconto_value(
        self,
        company_id: int,
        kind_id: int,
        name: str,
        code: str | None = None,
        owner_id: int | None = None,
        *,
        parent_id: int | None = None,
        is_group: bool = False,
    ) -> int:
        """Add a directory element; `owner_id` — the counterparty a contract belongs to,
        `parent_id` — the group it is in. With `is_group` it is a group (a folder): it
        holds elements and is never chosen on a posting."""
        with transaction(self.conn):
            self._check_owner(company_id, kind_id, owner_id)
            self._check_parent(company_id, kind_id, parent_id)
            try:
                columns = ["company_id", "kind_id", "code", "name", "owner_id"]
                params: list[object] = [company_id, kind_id, code, name, owner_id]
                if parent_id is not None or is_group:  # named only when used (D60)
                    columns += ["parent_id", "is_group"]
                    params += [parent_id, int(is_group)]
                value_id = insert(
                    self.conn,
                    f"INSERT INTO subconto_values ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' * len(columns))})",
                    params,
                )
            except IntegrityError as e:
                raise ValidationError(
                    tr("не удалось добавить субконто {name}: {error}", name=name, error=e)
                ) from e
            details: dict[str, object] = {"kind_id": kind_id, "name": name, "owner_id": owner_id}
            if parent_id is not None:
                details["parent_id"] = parent_id
            if is_group:
                details["group"] = True
            self._audit(company_id, "subconto_value", value_id, "create", details)
        return value_id

    def add_subconto_group(
        self, company_id: int, kind_id: int, name: str, parent_id: int | None = None
    ) -> int:
        """A group (folder) of a directory: «Kabellər», «Xarici təchizatçılar»."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название не может быть пустым"))
        return self.add_subconto_value(
            company_id, kind_id, name, parent_id=parent_id, is_group=True
        )

    def set_subconto_value_parent(
        self, company_id: int, value_id: int, parent_id: int | None
    ) -> None:
        """Move an element (or a group with all it holds) into a group, or out of any.
        Postings keep the element, so reports by element do not change."""
        with transaction(self.conn):
            value = self._subconto_value(company_id, value_id)
            if value["parent_id"] == parent_id:
                return
            self._check_parent(company_id, value["kind_id"], parent_id)
            ancestor = parent_id
            while ancestor is not None:  # not into itself or a group inside it
                if ancestor == value_id:
                    raise ValidationError(tr("группу нельзя перенести в неё саму"))
                ancestor = self._subconto_value(company_id, ancestor)["parent_id"]
            self.conn.execute(
                "UPDATE subconto_values SET parent_id = ? WHERE id = ?", (parent_id, value_id)
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "move",
                {"from": value["parent_id"], "to": parent_id},
            )

    def _check_parent(self, company_id: int, kind_id: int, parent_id: int | None) -> None:
        if parent_id is None:
            return
        parent = self._subconto_value(company_id, parent_id)
        if parent["kind_id"] != kind_id or not parent["is_group"]:
            raise ValidationError(tr("«{name}» — не группа этого справочника", name=parent["name"]))

    def update_subconto_value(
        self, company_id: int, value_id: int, name: str, code: str | None = None
    ) -> None:
        """Rename a directory element. Postings reference it by id, so history follows."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название не может быть пустым"))
        with transaction(self.conn):
            old = self._subconto_value(company_id, value_id)
            try:
                self.conn.execute(
                    "UPDATE subconto_values SET name = ?, code = ? WHERE id = ?",
                    (name, code, value_id),
                )
            except IntegrityError as e:
                raise ValidationError(
                    tr("не удалось добавить субконто {name}: {error}", name=name, error=e)
                ) from e
            self._audit(
                company_id, "subconto_value", value_id, "rename", {"from": old["name"], "to": name}
            )

    def set_subconto_value_legal_name(
        self, company_id: int, value_id: int, legal_name: str | None
    ) -> None:
        """A counterparty's official name as the tax portal writes it (not its name here)."""
        legal_name = " ".join((legal_name or "").split()) or None
        with transaction(self.conn):
            old = self._subconto_value(company_id, value_id)
            if old["legal_name"] == legal_name:
                return
            self.conn.execute(
                "UPDATE subconto_values SET legal_name = ? WHERE id = ?", (legal_name, value_id)
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "legal_name",
                {"from": old["legal_name"], "to": legal_name},
            )

    def set_subconto_value_active(self, company_id: int, value_id: int, active: bool) -> None:
        """Hide an element from entry lists (history and reports keep it), or show it again."""
        with transaction(self.conn):
            self._subconto_value(company_id, value_id)
            self.conn.execute(
                "UPDATE subconto_values SET active = ? WHERE id = ?", (int(active), value_id)
            )
            self._audit(company_id, "subconto_value", value_id, "show" if active else "hide", {})

    def delete_subconto_value(self, company_id: int, value_id: int) -> None:
        """Delete a directory element entered by mistake, if nothing refers to it: no
        postings (drafts count), contracts of its own, templates, documents of the modules.
        A used one can be hidden. An item or a warehouse goes through `Inventory.delete_value`."""
        with transaction(self.conn):
            value = self._subconto_value(company_id, value_id)
            reason = where_used(self.conn, company_id, "subconto_values", value_id)
            if reason is not None:
                raise ValidationError(
                    tr(
                        "«{name}» нельзя удалить: {reason}. Его можно скрыть.",
                        name=value["name"],
                        reason=reason,
                    )
                )
            self.conn.execute("DELETE FROM subconto_values WHERE id = ?", (value_id,))
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "delete",
                {"kind_id": value["kind_id"], "name": value["name"]},
            )

    def set_subconto_value_currency(
        self, company_id: int, value_id: int, currency_id: int | None
    ) -> None:
        """Currency of a directory element (a USD bank account, a contract in EUR): offered
        when the element is chosen on a currency account and checked when posting."""
        with transaction(self.conn):
            old = self._subconto_value(company_id, value_id)
            if currency_id is not None:
                self._currency(company_id, currency_id)
            self.conn.execute(
                "UPDATE subconto_values SET currency_id = ? WHERE id = ?", (currency_id, value_id)
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "set_currency",
                {"from": old["currency_id"], "to": currency_id},
            )

    def set_subconto_value_tax(
        self,
        company_id: int,
        value_id: int,
        tax_id: str | None,
        nonresident: bool = False,
        country: str | None = None,
    ) -> None:
        """Tax details of a counterparty: a resident's VÖEN (10 digits, may be unknown),
        or a non-resident's country and tax number of its own country (any format).
        Another counterparty with the same VÖEN is allowed (branches): the UI warns."""
        country = (country or "").strip() or None
        if nonresident:
            tax_id = " ".join((tax_id or "").split()) or None
        else:
            country = None
            tax_id = resident_tax_id(tax_id)
        with transaction(self.conn):
            old = self._subconto_value(company_id, value_id)
            self.conn.execute(
                "UPDATE subconto_values SET tax_id = ?, nonresident = ?, country = ? WHERE id = ?",
                (tax_id, int(nonresident), country, value_id),
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "set_tax",
                {
                    "from": [old["tax_id"], bool(old["nonresident"]), old["country"]],
                    "to": [tax_id, nonresident, country],
                },
            )

    def set_subconto_value_owner(
        self, company_id: int, value_id: int, owner_id: int | None
    ) -> None:
        """Give a contract its counterparty (or make it common to all with None).
        A contract already posted next to another counterparty cannot be given away."""
        with transaction(self.conn):
            old = self._subconto_value(company_id, value_id)
            owner_kind = self._check_owner(company_id, old["kind_id"], owner_id)
            if owner_id is not None and owner_kind is not None:
                others = self._partners(company_id, value_id, owner_kind) - {owner_id}
                if others:
                    other = self._subconto_value(company_id, min(others))
                    raise ValidationError(
                        tr(
                            "«{name}» уже есть в проводках с «{other}»",
                            name=old["name"],
                            other=other["name"],
                        )
                    )
            self.conn.execute(
                "UPDATE subconto_values SET owner_id = ? WHERE id = ?", (owner_id, value_id)
            )
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "set_owner",
                {"from": old["owner_id"], "to": owner_id},
            )

    # ---- tags (D64) -------------------------------------------------------------------

    def set_optional_subconto(
        self, company_id: int, account: int | str, positions: Iterable[int]
    ) -> None:
        """The account's subconto positions (0-2) that may stay empty: 70 paid in one sum,
        without an employee (D78). A position turns required again only while no posting
        has left it empty — it would not post again."""
        with transaction(self.conn):
            acc = self._account(company_id, account)
            label = account_label(acc)
            bits = 0
            for position in set(positions):
                if not 0 <= position <= 2 or acc[f"sc{position + 1}_kind_id"] is None:
                    raise ValidationError(
                        tr("счёт {code}: нет субконто {i}", code=label, i=position + 1)
                    )
                bits |= 1 << position
            for position in range(3):
                required_now = acc["sc_optional"] & (1 << position) and not bits & (1 << position)
                if required_now and self._left_empty(company_id, acc["id"], position + 1):
                    kind = self.conn.execute(
                        "SELECT name FROM subconto_kinds WHERE company_id = ? AND id = ?",
                        (company_id, acc[f"sc{position + 1}_kind_id"]),
                    ).fetchone()["name"]
                    raise ValidationError(
                        tr(
                            "счёт {code}: есть проводки без «{kind}», оно останется необязательным",
                            code=label,
                            kind=kind,
                        )
                    )
            self.conn.execute(
                "UPDATE accounts SET sc_optional = ? WHERE company_id = ? AND id = ?",
                (bits, company_id, acc["id"]),
            )
            self._audit(
                company_id,
                "account",
                acc["id"],
                "update",
                {"sc_optional": [acc["sc_optional"], bits]},
            )

    def _left_empty(self, company_id: int, account_id: int, i: int) -> bool:
        return (
            self.conn.execute(
                f"SELECT 1 FROM postings WHERE company_id = ? AND ("
                f"(debit_account_id = ? AND dt_sc{i} IS NULL) OR "
                f"(credit_account_id = ? AND ct_sc{i} IS NULL)) LIMIT 1",
                (company_id, account_id, account_id),
            ).fetchone()
            is not None
        )

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
        name = " ".join(name.split())
        with transaction(self.conn):
            old = self._tag(company_id, tag_id)
            if old["name"] == name:
                return
            self._check_tag_name(company_id, name, tag_id)
            self.conn.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
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
            self.conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
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
                raise ValidationError(tr("у группы не бывает меток — только у элементов"))
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
                "DELETE FROM subconto_value_tags WHERE value_id = ? AND tag_id = ?",
                [(value_id, t) for t in old - wanted],
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
            raise NotFoundError(tr("метка не найдена"))
        return row

    def _check_tag_name(self, company_id: int, name: str, tag_id: int | None = None) -> None:
        """Not empty, and not another tag's name (any case, İ and i alike)."""
        if not name:
            raise ValidationError(tr("название не может быть пустым"))
        for r in self.conn.execute("SELECT id, name FROM tags WHERE company_id = ?", (company_id,)):
            if r["id"] != tag_id and fold(r["name"]) == fold(name):
                raise ValidationError(tr("метка «{name}» уже есть", name=r["name"]))

    def _check_owner(self, company_id: int, kind_id: int, owner_id: int | None) -> int | None:
        """The owner must be an element of the directory that owns `kind_id`.
        Returns that directory (None if the kind has no owner)."""
        kind = self.conn.execute(
            "SELECT owner_kind_id FROM subconto_kinds WHERE company_id = ? AND id = ?",
            (company_id, kind_id),
        ).fetchone()
        if kind is None:
            raise NotFoundError(tr("справочник не найден"))
        if owner_id is None:
            return kind["owner_kind_id"]
        if kind["owner_kind_id"] is None:
            raise ValidationError(tr("у элементов этого справочника не бывает владельца"))
        owner = self._subconto_value(company_id, owner_id)
        if owner["kind_id"] != kind["owner_kind_id"]:
            owner_kind = self.conn.execute(
                "SELECT name FROM subconto_kinds WHERE id = ?", (kind["owner_kind_id"],)
            ).fetchone()
            raise ValidationError(
                tr("владелец должен быть из справочника «{kind}»", kind=owner_kind["name"])
            )
        return kind["owner_kind_id"]

    def _partners(self, company_id: int, value_id: int, owner_kind: int) -> set[int]:
        """Elements of `owner_kind` posted on the same side as `value_id`."""
        found: set[int] = set()
        for side, prefix in (("debit", "dt"), ("credit", "ct")):
            rows = self.conn.execute(
                f"SELECT a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id, "
                f"p.{prefix}_sc1, p.{prefix}_sc2, p.{prefix}_sc3 "
                f"FROM postings p JOIN accounts a ON a.id = p.{side}_account_id "
                f"WHERE p.company_id = ? AND ? IN (p.{prefix}_sc1, p.{prefix}_sc2, p.{prefix}_sc3)",
                (company_id, value_id),
            )
            for r in rows:
                for i in range(3):
                    if r[i] == owner_kind and r[3 + i] is not None:
                        found.add(r[3 + i])
        return found
