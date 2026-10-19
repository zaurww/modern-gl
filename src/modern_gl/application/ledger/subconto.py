"""Subconto kinds (directories) and their values."""

from __future__ import annotations

import sqlite3

from modern_gl.application.common import insert
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class SubcontoCommands(LedgerBase):
    def add_subconto_kind(self, company_id: int, code: str | None, name: str) -> int:
        """Add a directory. Without a code (user-made directories) one is generated."""
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
                "INSERT INTO subconto_kinds (company_id, code, name) VALUES (?, ?, ?)",
                (company_id, code, name),
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
        self, company_id: int, kind_id: int, name: str, code: str | None = None
    ) -> int:
        with transaction(self.conn):
            try:
                value_id = insert(
                    self.conn,
                    "INSERT INTO subconto_values (company_id, kind_id, code, name) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, kind_id, code, name),
                )
            except sqlite3.IntegrityError as e:
                raise ValidationError(
                    tr("не удалось добавить субконто {name}: {error}", name=name, error=e)
                ) from e
            self._audit(
                company_id, "subconto_value", value_id, "create", {"kind_id": kind_id, "name": name}
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
