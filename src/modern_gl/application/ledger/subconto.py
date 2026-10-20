"""Subconto kinds (directories) and their values."""

from __future__ import annotations

import sqlite3

from modern_gl.application.common import insert
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


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
        row = self.conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = ?", (company_id, code)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("вид субконто {code} не найден", code=code))
        return row["id"]

    def add_subconto_value(
        self,
        company_id: int,
        kind_id: int,
        name: str,
        code: str | None = None,
        owner_id: int | None = None,
    ) -> int:
        """Add a directory element; `owner_id` — the counterparty a contract belongs to."""
        with transaction(self.conn):
            self._check_owner(company_id, kind_id, owner_id)
            try:
                value_id = insert(
                    self.conn,
                    "INSERT INTO subconto_values (company_id, kind_id, code, name, owner_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (company_id, kind_id, code, name, owner_id),
                )
            except sqlite3.IntegrityError as e:
                raise ValidationError(
                    tr("не удалось добавить субконто {name}: {error}", name=name, error=e)
                ) from e
            self._audit(
                company_id,
                "subconto_value",
                value_id,
                "create",
                {"kind_id": kind_id, "name": name, "owner_id": owner_id},
            )
        return value_id

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
            except sqlite3.IntegrityError as e:
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
        tax_id = " ".join((tax_id or "").split()) or None
        country = (country or "").strip() or None
        if not nonresident:
            country = None
            if tax_id is not None:
                tax_id = tax_id.replace(" ", "")
                if not (tax_id.isdigit() and len(tax_id) == 10):
                    raise ValidationError(tr("VÖEN — 10 цифр, а не «{text}»", text=tax_id))
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
