"""In-memory lookup of one company's chart of accounts and subconto values.

Used by the entry UI to resolve what the user typed ("60.1", "касса", "Альфа")
into ids. Plain Python, no Qt, so it is unit-testable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountInfo:
    id: int
    code: str
    name: str
    kind: str
    is_group: bool
    parent_id: int | None
    sc_kinds: tuple[int | None, int | None, int | None]

    @property
    def label(self) -> str:
        return f"{self.code}  {self.name}"


@dataclass(frozen=True)
class SubcontoInfo:
    id: int
    kind_id: int
    name: str
    code: str | None

    @property
    def label(self) -> str:
        return self.name


class Catalog:
    def __init__(self, conn: sqlite3.Connection, company_id: int) -> None:
        self.conn = conn
        self.company_id = company_id
        self.reload()

    def reload(self) -> None:
        self.accounts: dict[int, AccountInfo] = {
            r["id"]: AccountInfo(
                r["id"],
                r["code"],
                r["name"],
                r["kind"],
                bool(r["is_group"]),
                r["parent_id"],
                (r["sc1_kind_id"], r["sc2_kind_id"], r["sc3_kind_id"]),
            )
            for r in self.conn.execute(
                "SELECT * FROM accounts WHERE company_id = ? AND active = 1 ORDER BY code",
                (self.company_id,),
            )
        }
        self.by_code = {a.code: a for a in self.accounts.values()}
        self.kinds: dict[int, str] = {
            r["id"]: r["name"]
            for r in self.conn.execute(
                "SELECT id, name FROM subconto_kinds WHERE company_id = ?", (self.company_id,)
            )
        }
        self._values: dict[int, SubcontoInfo] = {}
        self._by_kind: dict[int, list[SubcontoInfo]] = {k: [] for k in self.kinds}
        for r in self.conn.execute(
            "SELECT id, kind_id, name, code FROM subconto_values "
            "WHERE company_id = ? AND active = 1 ORDER BY name",
            (self.company_id,),
        ):
            self._add(SubcontoInfo(r["id"], r["kind_id"], r["name"], r["code"]))

    def _add(self, value: SubcontoInfo) -> None:
        self._values[value.id] = value
        self._by_kind.setdefault(value.kind_id, []).append(value)

    def add_value(self, value_id: int, kind_id: int, name: str, code: str | None = None) -> None:
        """Register a value just created through the Ledger, without a full reload."""
        self._add(SubcontoInfo(value_id, kind_id, name, code))
        self._by_kind[kind_id].sort(key=lambda v: v.name.casefold())

    @property
    def leaf_accounts(self) -> list[AccountInfo]:
        return [a for a in self.accounts.values() if not a.is_group]

    def values(self, kind_id: int) -> list[SubcontoInfo]:
        return self._by_kind.get(kind_id, [])

    def value(self, value_id: int) -> SubcontoInfo:
        return self._values[value_id]

    def used_positions(self) -> set[int]:
        """Subconto positions (1..3) used by at least one account."""
        return {i + 1 for a in self.accounts.values() for i, k in enumerate(a.sc_kinds) if k}

    def resolve_account(self, text: str) -> AccountInfo:
        """'60.1', '60.1  Расчёты…' or a unique fragment of a name -> postable account."""
        text = text.strip()
        if not text:
            raise LookupError("счёт не указан")
        found = self.by_code.get(text.split()[0])
        if found is None:
            needle = text.casefold()
            matches = [a for a in self.leaf_accounts if needle in a.name.casefold()]
            if len(matches) > 1:  # prefer names that start with what was typed
                starts = [a for a in matches if a.name.casefold().startswith(needle)]
                matches = starts if len(starts) == 1 else matches
            if len(matches) != 1:
                if not matches:
                    raise LookupError(f"счёт «{text}» не найден")
                codes = ", ".join(a.code for a in matches[:6])
                raise LookupError(f"«{text}» подходит к нескольким счетам: {codes}")
            found = matches[0]
        if found.is_group:
            subs = ", ".join(a.code for a in self.accounts.values() if a.parent_id == found.id)
            raise LookupError(f"счёт {found.code} — группа, выберите субсчёт: {subs}")
        return found

    def resolve_value(self, kind_id: int, text: str) -> int | None:
        """Exact or unique partial name match; None if nothing matches."""
        needle = text.strip().casefold()
        values = self.values(kind_id)
        exact = [v for v in values if v.name.casefold() == needle or (v.code or "") == text.strip()]
        if exact:
            return exact[0].id
        partial = [v for v in values if needle in v.name.casefold()]
        if len(partial) > 1:
            names = ", ".join(v.name for v in partial[:5])
            raise LookupError(f"«{text}» подходит к нескольким: {names}")
        return partial[0].id if partial else None
