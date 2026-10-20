"""In-memory lookup of one company's chart of accounts and subconto values.

Used by the entry UI to resolve what the user typed ("60.1", "касса", "Альфа")
into ids. Plain Python, no Qt, so it is unit-testable.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.application.currencies import CurrencyInfo, list_currencies
from modern_gl.domain.accounts import SETTLEMENT_TYPES, VAT_TYPES
from modern_gl.domain.currency import CURRENCY_OPTIONAL
from modern_gl.i18n import fold, sort_key, tr


@dataclass(frozen=True)
class AccountInfo:
    id: int
    code: str  # "" when the account has no code (known by its name only)
    name: str
    is_group: bool
    parent_id: int | None
    sc_kinds: tuple[int | None, int | None, int | None]
    account_class: str | None = None
    contra: bool = False
    active: bool = True
    two_sided: bool = False
    currency: int = 0  # domain.currency mode: 0 manat, 1 only in currency, 2 either
    account_type: str | None = None  # domain.accounts.ACCOUNT_TYPES

    @property
    def currency_optional(self) -> bool:
        """Postings may be in manat or in a currency (60, 62)."""
        return self.currency == CURRENCY_OPTIONAL

    @property
    def label(self) -> str:
        return f"{self.code}  {self.name}" if self.code else self.name

    @property
    def short(self) -> str:
        """Code if there is one, else the name: for grid cells and messages."""
        return self.code or self.name


@dataclass(frozen=True)
class SubcontoInfo:
    id: int
    kind_id: int
    name: str
    code: str | None
    active: bool = True
    currency_id: int | None = None  # a USD bank account, a contract in EUR
    owner_id: int | None = None  # the counterparty a contract belongs to (None: common)
    tax_id: str | None = None  # a counterparty's VÖEN, or a non-resident's own tax number
    nonresident: bool = False
    country: str | None = None  # of a non-resident

    @property
    def label(self) -> str:
        """The name, and the VÖEN after it: lists find a counterparty by either."""
        return f"{self.name}  ·  {self.tax_id}" if self.tax_id else self.name


class Catalog:
    def __init__(self, conn: sqlite3.Connection, company_id: int) -> None:
        self.conn = conn
        self.company_id = company_id
        self.reload()

    def reload(self) -> None:
        self.accounts: dict[int, AccountInfo] = {
            r["id"]: AccountInfo(
                r["id"],
                r["code"] or "",
                r["name"],
                bool(r["is_group"]),
                r["parent_id"],
                (r["sc1_kind_id"], r["sc2_kind_id"], r["sc3_kind_id"]),
                r["account_class"],
                bool(r["contra"]),
                bool(r["active"]),
                bool(r["two_sided"]),
                r["currency"],
                r["account_type"],
            )
            for r in self.conn.execute(
                "SELECT * FROM accounts WHERE company_id = ? ORDER BY code IS NULL, code",
                (self.company_id,),
            )
        }
        self._tree_order()
        self.by_code = {a.code: a for a in self.accounts.values() if a.code}
        kinds = self.conn.execute(
            "SELECT id, code, name, owner_kind_id FROM subconto_kinds WHERE company_id = ?",
            (self.company_id,),
        ).fetchall()
        self.kinds: dict[int, str] = {r["id"]: r["name"] for r in kinds}
        self.kind_codes: dict[int, str] = {r["id"]: r["code"] for r in kinds}
        # contracts -> counterparties: elements of a kind belong to elements of another
        self.owner_kinds: dict[int, int] = {
            r["id"]: r["owner_kind_id"] for r in kinds if r["owner_kind_id"] is not None
        }
        self._values: dict[int, SubcontoInfo] = {}
        self._by_kind: dict[int, list[SubcontoInfo]] = {k: [] for k in self.kinds}
        for r in self.conn.execute(
            "SELECT id, kind_id, name, code, active, currency_id, owner_id, tax_id, "
            "nonresident, country FROM subconto_values WHERE company_id = ? ORDER BY name",
            (self.company_id,),
        ):
            self._add(
                SubcontoInfo(
                    r["id"],
                    r["kind_id"],
                    r["name"],
                    r["code"],
                    bool(r["active"]),
                    r["currency_id"],
                    r["owner_id"],
                    r["tax_id"],
                    bool(r["nonresident"]),
                    r["country"],
                )
            )
        for values in self._by_kind.values():
            values.sort(key=lambda v: sort_key(v.name))
        self.currencies: dict[int, CurrencyInfo] = {
            c.id: c for c in list_currencies(self.conn, self.company_id)
        }

    def _tree_order(self) -> None:
        """Tree order: each account followed by its subaccounts; among siblings coded
        accounts come first (by code), then the ones without a code (alphabetically)."""
        children: dict[int | None, list[AccountInfo]] = {}
        for a in self.accounts.values():  # already ordered by code
            children.setdefault(a.parent_id, []).append(a)
        for siblings in children.values():
            siblings.sort(key=lambda a: (not a.code, "" if a.code else sort_key(a.name)))
        ordered: dict[int, AccountInfo] = {}
        stack = list(reversed(children.get(None, [])))
        while stack:
            a = stack.pop()
            ordered[a.id] = a
            stack.extend(reversed(children.get(a.id, [])))
        self.accounts = ordered

    def _add(self, value: SubcontoInfo) -> None:
        self._values[value.id] = value
        self._by_kind.setdefault(value.kind_id, []).append(value)

    def add_value(
        self,
        value_id: int,
        kind_id: int,
        name: str,
        code: str | None = None,
        owner_id: int | None = None,
    ) -> None:
        """Register a value just created through the Ledger, without a full reload."""
        self._add(SubcontoInfo(value_id, kind_id, name, code, owner_id=owner_id))
        self._by_kind[kind_id].sort(key=lambda v: sort_key(v.name))

    @property
    def leaf_accounts(self) -> list[AccountInfo]:
        """Accounts that can be posted to (hidden accounts are not offered)."""
        return [a for a in self.accounts.values() if not a.is_group and a.active]

    def group_named(self, text: str) -> AccountInfo | None:
        """The group whose code, name or label is exactly the text ("68", "68  Vergilər")."""
        needle = fold(text.strip())
        if not needle:
            return None
        return next(
            (
                a
                for a in self.accounts.values()
                if a.is_group
                and a.active
                and needle in {fold(a.code or ""), fold(a.name), fold(a.label)}
            ),
            None,
        )

    def subaccounts(self, group: AccountInfo) -> list[AccountInfo]:
        """Postable accounts under a group, nested groups unfolded, in chart order."""
        ids = {group.id}
        for a in self.accounts.values():  # parents come before their children
            if a.parent_id in ids:
                ids.add(a.id)
        return [a for a in self.leaf_accounts if a.id in ids and a.id != group.id]

    def values(self, kind_id: int, owner: int | None = None) -> list[SubcontoInfo]:
        """Values offered for entry (hidden ones are not). With an `owner` (the chosen
        counterparty) a contract list shows its contracts and the common ones only."""
        return [
            v
            for v in self._by_kind.get(kind_id, [])
            if v.active and (owner is None or v.owner_id in (None, owner))
        ]

    def owner_title(self, kind_id: int) -> str:
        """What one owner is called: "Контрагент" (a directory is named in plural)."""
        owner = self.owner_kinds[kind_id]
        return (
            tr("Контрагент") if self.kind_codes.get(owner) == "counterparty" else self.kinds[owner]
        )

    def owner_slot(self, account: AccountInfo, pos: int) -> int | None:
        """Position (0..2) on the account of the owner of position `pos`: where the
        counterparty of a contract is. None if the kind has no owner or it is not there."""
        owner_kind = self.owner_kinds.get(account.sc_kinds[pos] or 0)
        if owner_kind is None:
            return None
        return next((i for i, k in enumerate(account.sc_kinds) if k == owner_kind), None)

    def owner_in(self, account: AccountInfo, values: Sequence[int | None], pos: int) -> int | None:
        """The owner chosen on the same side for position `pos` (the line's counterparty)."""
        slot = self.owner_slot(account, pos)
        return values[slot] if slot is not None else None

    def owned_elsewhere(self, value_id: int, owner: int | None) -> bool:
        """The element belongs to another owner than the one chosen."""
        value = self._values[value_id]
        return owner is not None and value.owner_id not in (None, owner)

    def takes_invoice(self, account_id: int | None) -> bool:
        """A line on the account may name its e-qaimə: settlements with partners (an
        account with the counterparty directory, or of a settlement type) and ƏDV."""
        if account_id is None:
            return False
        account = self.accounts[account_id]
        if account.account_type is not None:
            return account.account_type in SETTLEMENT_TYPES | VAT_TYPES
        return any(self.kind_codes.get(k or 0) == "counterparty" for k in account.sc_kinds)

    def has_tax_id(self, kind_id: int) -> bool:
        """Elements of the directory are counterparties: they have a VÖEN."""
        return self.kind_codes.get(kind_id) == "counterparty"

    def same_tax_id(self, kind_id: int, tax_id: str, except_id: int | None = None) -> list[str]:
        """Names of the other elements with this VÖEN (a counterparty entered twice)."""
        return [
            v.name
            for v in self._by_kind.get(kind_id, [])
            if v.tax_id == tax_id and v.id != except_id
        ]

    def all_values(self, kind_id: int) -> list[SubcontoInfo]:
        """Every value of a directory, hidden ones included."""
        return list(self._by_kind.get(kind_id, []))

    def accounts_using(self, kind_id: int) -> list[AccountInfo]:
        return [a for a in self.accounts.values() if kind_id in a.sc_kinds]

    def value(self, value_id: int) -> SubcontoInfo:
        return self._values[value_id]

    @property
    def active_currencies(self) -> list[CurrencyInfo]:
        return [c for c in self.currencies.values() if c.active]

    @property
    def has_currency_accounts(self) -> bool:
        return any(a.currency for a in self.accounts.values())

    def resolve_currency(self, text: str) -> CurrencyInfo:
        """'USD', 'usd', 'USD  ABŞ dolları' or a unique fragment of a name."""
        needle = fold(text.strip())
        if not needle:
            raise LookupError(tr("валюта не указана"))
        code = needle.split()[0].upper()
        found = [c for c in self.active_currencies if c.code == code]
        if not found:
            found = [c for c in self.active_currencies if needle in fold(c.label)]
        if len(found) != 1:
            if not found:
                raise LookupError(tr("валюта «{text}» не найдена", text=text.strip()))
            codes = ", ".join(c.code for c in found[:6])
            raise LookupError(
                tr("«{text}» подходит к нескольким валютам: {codes}", text=text, codes=codes)
            )
        return found[0]

    def used_positions(self) -> set[int]:
        """Subconto positions (1..3) used by at least one account."""
        return {i + 1 for a in self.accounts.values() for i, k in enumerate(a.sc_kinds) if k}

    def resolve_account(self, text: str) -> AccountInfo:
        """'60.1', '60.1  Расчёты…' or a unique fragment of a name -> postable account."""
        text = text.strip()
        if not text:
            raise LookupError(tr("счёт не указан"))
        found = self.by_code.get(text.split()[0])
        if found is None:
            needle = fold(text)
            matches = [a for a in self.leaf_accounts if needle in fold(a.label)]
            if len(matches) > 1:  # prefer the exact name, then names starting with the text
                exact = [a for a in matches if fold(a.name) == needle or fold(a.label) == needle]
                starts = [a for a in matches if fold(a.name).startswith(needle)]
                matches = exact or (starts if len(starts) == 1 else matches)
            if len(matches) != 1:
                if not matches:
                    raise LookupError(tr("счёт «{text}» не найден", text=text))
                codes = ", ".join(a.short for a in matches[:6])
                raise LookupError(
                    tr("«{text}» подходит к нескольким счетам: {codes}", text=text, codes=codes)
                )
            found = matches[0]
        if not found.active:
            raise LookupError(tr("счёт {code} скрыт", code=found.short))
        if found.is_group:
            subs = ", ".join(a.short for a in self.accounts.values() if a.parent_id == found.id)
            raise LookupError(
                tr("счёт {code} — группа, выберите субсчёт: {subs}", code=found.short, subs=subs)
            )
        return found

    def resolve_value(self, kind_id: int, text: str, owner: int | None = None) -> int | None:
        """Exact or unique partial name match; None if nothing matches. With an `owner`
        only its elements and the common ones are looked at (each counterparty may have
        its own "Фактура 15")."""
        needle = fold(text.strip())
        values = self.values(kind_id, owner)
        exact = [
            v
            for v in values
            if needle in (fold(v.name), fold(v.label))
            or (v.tax_id is not None and fold(v.tax_id) == needle)
            or (v.code or "") == text.strip()
        ]
        if len({v.owner_id for v in exact}) > 1:  # "Фактура 15" of two counterparties
            raise LookupError(
                tr("«{text}» есть у нескольких: сначала укажите, чей", text=text.strip())
            )
        if exact:
            return exact[0].id
        partial = [v for v in values if needle in fold(v.label)]
        if len(partial) > 1:
            starts = [v for v in partial if fold(v.name).startswith(needle)]
            partial = starts if len(starts) == 1 else partial
        if len(partial) > 1:
            names = ", ".join(v.name for v in partial[:5])
            raise LookupError(tr("«{text}» подходит к нескольким: {names}", text=text, names=names))
        return partial[0].id if partial else None


def search(labels: list[str], text: str) -> list[str]:
    """Filter completion labels: names/codes starting with the text first, then containing it."""
    needle = fold(text.strip())
    if not needle:
        return list(labels)
    starts, contains = [], []
    for label in labels:
        f = fold(label)
        words = f.split()
        if f.startswith(needle) or any(w.startswith(needle) for w in words):
            starts.append(label)
        elif needle in f:
            contains.append(label)
    return starts + contains
