"""The chart of accounts."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.common import insert, pad_subconto, where_used
from modern_gl.application.ledger.account_types import AccountTypeCommands
from modern_gl.application.ledger.base import account_label, clean_code
from modern_gl.domain.accounts import ACCOUNT_ROLES, ROLE_TYPES
from modern_gl.domain.currency import CURRENCY_ONLY, NO_CURRENCY, currency_mode
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import IntegrityError, Row, transaction


def _inherited(
    parent: Row,
    account_class: str | None,
    account_type: str | None,
    two_sided: bool | None,
    currency: bool | int | None,
) -> tuple[str | None, str | None, bool, bool | int | None]:
    """What a subaccount takes from its group unless given: the class, the type (when the
    class is the group's), two-sidedness and the currency mode."""
    account_class = account_class or parent["account_class"]
    if account_type is None and account_class == parent["account_class"]:
        account_type = parent["account_type"]
    if two_sided is None:
        two_sided = bool(parent["two_sided"])
    if currency is None:
        currency = parent["currency"]
    return account_class, account_type, two_sided, currency


class ChartCommands(AccountTypeCommands):
    def add_account(
        self,
        company_id: int,
        code: str | None,
        name: str,
        *,
        parent: int | str | None = None,
        is_group: bool = False,
        subconto: Sequence[int] = (),
        account_class: str | None = None,
        account_type: str | None = None,
        contra: bool = False,
        two_sided: bool | None = None,
        currency: bool | int | None = None,
    ) -> int:
        """Add an account. `subconto` lists subconto kind ids for positions 1..3.

        The code is optional (empty: the account is known by its name). `parent` is the
        parent account's id or code. Without `account_class` the account inherits its
        parent's class (or stays unclassified). `account_type` (domain.accounts.ACCOUNT_TYPES)
        gives the class; without it the account takes its parent's type if it has the
        parent's class. `two_sided` (balance may be on either
        side, shown expanded per first subconto) is inherited from the parent unless given,
        and so is `currency`: a mode of domain.currency (CURRENCY_ONLY, CURRENCY_OPTIONAL;
        True means CURRENCY_ONLY).
        """
        code = clean_code(code)
        name = name.strip()
        label = code or name
        if not name:
            raise ValidationError(tr("название счёта не может быть пустым"))
        self._check_class(label, account_class)
        account_class = self._class_of_type(label, account_type, account_class)
        if is_group and subconto:
            raise ValidationError(tr("счёт {code}: у группы не бывает субконто", code=label))
        sc = pad_subconto(subconto)
        with transaction(self.conn):
            parent_id = None
            if parent is not None:
                parent_row = self._group_parent(company_id, parent, label)
                parent_id = parent_row["id"]
                account_class, account_type, two_sided, currency = _inherited(
                    parent_row, account_class, account_type, two_sided, currency
                )
            mode = currency_mode(currency or NO_CURRENCY)
            account_id = self._insert_account(
                label,
                (
                    company_id,
                    code,
                    name,
                    parent_id,
                    int(is_group),
                    *sc,
                    account_class,
                    account_type,
                    int(contra),
                    int(bool(two_sided)),
                    mode,
                ),
            )
            self._audit(
                company_id,
                "account",
                account_id,
                "create",
                {
                    "code": code,
                    "name": name,
                    "class": account_class,
                    "type": account_type,
                    "two_sided": bool(two_sided),
                    "currency": mode,
                },
            )
        return account_id

    def _group_parent(self, company_id: int, parent: int | str, label: str) -> Row:
        """The parent of a new account: an existing group."""
        parent_row = self._account(company_id, parent)
        if not parent_row["is_group"]:
            raise ValidationError(
                tr(
                    "счёт {code}: родитель {parent} не группа",
                    code=label,
                    parent=account_label(parent_row),
                )
            )
        return parent_row

    def _insert_account(self, label: str, values: tuple) -> int:
        """The new row of accounts; a code already taken is told as such."""
        try:
            return insert(
                self.conn,
                "INSERT INTO accounts (company_id, code, name, parent_id, is_group, "
                "sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, account_type, contra, "
                "two_sided, currency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        except IntegrityError as e:
            if "UNIQUE" in str(e):
                raise ValidationError(tr("счёт {code} уже есть", code=label)) from e
            raise ValidationError(
                tr("не удалось добавить счёт {code}: {error}", code=label, error=e)
            ) from e

    def account_id(self, company_id: int, code: str) -> int:
        return self._account(company_id, code)["id"]

    def update_account(
        self,
        company_id: int,
        account: int | str,
        *,
        new_code: str | None = None,
        name: str | None = None,
        two_sided: bool | None = None,
        is_group: bool | None = None,
        subconto: Sequence[int] | None = None,
        currency: bool | int | None = None,
    ) -> None:
        """Rename / re-code / reconfigure an account (given by id or code). Audited.

        `new_code=""` removes the code. History is protected: an account with postings
        cannot become a group and its subconto kinds cannot change (old postings carry
        values of those kinds); a kind may only be added at a free position, where it
        becomes optional (the old postings have no value there; D61). Currency accounting
        changes only as far as the old postings fit: "in manat or in a currency" always
        does; "manat only" needs no posting in a currency, "currency only" none in manat.
        Codes are only labels — postings reference the account id, so re-coding is safe.
        """
        with transaction(self.conn):
            acc = self._account(company_id, account)
            label = account_label(acc)
            new_code = acc["code"] if new_code is None else clean_code(new_code)
            name = acc["name"] if name is None else name.strip()
            two_sided = bool(acc["two_sided"]) if two_sided is None else bool(two_sided)
            group = bool(acc["is_group"]) if is_group is None else bool(is_group)
            mode: int = acc["currency"] if currency is None else currency_mode(currency)
            current_sc = (acc["sc1_kind_id"], acc["sc2_kind_id"], acc["sc3_kind_id"])
            sc = current_sc if subconto is None else pad_subconto(subconto)
            if not name:
                raise ValidationError(tr("название счёта не может быть пустым"))
            used = self._has_postings(acc["id"])
            if group != bool(acc["is_group"]):
                self._check_group_change(company_id, acc, label, group, used)
            if group:
                sc = (None, None, None)
            optional = self._optional_positions(acc, label, current_sc, sc, used)
            if mode != acc["currency"] and used:
                self._check_currency_fits(acc, label, mode)
            try:
                self.conn.execute(
                    "UPDATE accounts SET code = ?, name = ?, two_sided = ?, is_group = ?, "
                    "sc1_kind_id = ?, sc2_kind_id = ?, sc3_kind_id = ?, sc_optional = ?, "
                    "currency = ? WHERE id = ?",
                    (new_code, name, int(two_sided), int(group), *sc, optional, mode, acc["id"]),
                )
            except IntegrityError as e:
                raise ValidationError(tr("счёт {code} уже есть", code=new_code)) from e
            self._audit(
                company_id,
                "account",
                acc["id"],
                "update",
                {
                    "before": {
                        "code": acc["code"],
                        "name": acc["name"],
                        "two_sided": bool(acc["two_sided"]),
                        "group": bool(acc["is_group"]),
                        "subconto": current_sc,
                        "currency": acc["currency"],
                    },
                    "after": {
                        "code": new_code,
                        "name": name,
                        "two_sided": two_sided,
                        "group": group,
                        "subconto": sc,
                        "currency": mode,
                    },
                },
            )

    def _check_group_change(
        self, company_id: int, acc: Row, label: str, group: bool, used: bool
    ) -> None:
        """An account with postings does not become a group; a group with subaccounts
        stays one."""
        if group and used:
            raise ValidationError(
                tr(
                    "счёт {code}: по счёту есть проводки, он не может стать группой",
                    code=label,
                )
            )
        if (
            not group
            and self.conn.execute(
                "SELECT 1 FROM accounts WHERE company_id = ? AND parent_id = ?",
                (company_id, acc["id"]),
            ).fetchone()
        ):
            raise ValidationError(tr("счёт {code}: у группы есть субсчета", code=label))

    @staticmethod
    def _optional_positions(
        acc: Row,
        label: str,
        current_sc: tuple[int | None, ...],
        sc: tuple[int | None, ...],
        used: bool,
    ) -> int:
        """The subconto positions old postings have no value at (bits 0-2): a kind added
        to an account with postings goes to a free place only and is optional there (D61)."""
        optional = acc["sc_optional"] if used else 0
        if sc != current_sc and used:
            pairs = list(zip(current_sc, sc, strict=True))
            if any(old is not None and new != old for old, new in pairs):
                raise ValidationError(
                    tr(
                        "счёт {code}: по счёту есть проводки, субконто можно только "
                        "добавить на свободное место",
                        code=label,
                    )
                )
            for position, (old, new) in enumerate(pairs):
                if old is None and new is not None:  # old postings have no value there
                    optional |= 1 << position
        return optional

    def set_account_active(self, company_id: int, account: int | str, active: bool) -> None:
        """Hide an account from entry (history and reports stay intact), or show it again."""
        with transaction(self.conn):
            acc = self._account(company_id, account)
            self.conn.execute(
                "UPDATE accounts SET active = ? WHERE id = ?", (int(active), acc["id"])
            )
            self._audit(
                company_id,
                "account",
                acc["id"],
                "show" if active else "hide",
                {"code": acc["code"]},
            )

    def delete_account(self, company_id: int, account: int | str) -> None:
        """Delete an account entered by mistake. Only one nothing refers to: no postings
        (drafts count), subaccounts, items, templates, settings; a used one can be hidden."""
        with transaction(self.conn):
            acc = self._account(company_id, account)
            reason = where_used(self.conn, company_id, "accounts", acc["id"])
            if reason is not None:
                raise ValidationError(
                    tr(
                        "счёт {code} нельзя удалить: {reason}. Его можно скрыть.",
                        code=account_label(acc),
                        reason=reason,
                    )
                )
            self.conn.execute("DELETE FROM accounts WHERE id = ?", (acc["id"],))
            self._audit(
                company_id,
                "account",
                acc["id"],
                "delete",
                {"code": acc["code"], "name": acc["name"]},
            )

    def _check_currency_fits(self, account: Row, label: str, mode: int) -> None:
        """Old postings must fit the new currency accounting of the account. A manat-only
        account may already have postings in a currency — of the other side (51 in
        Dt 52 / Ct 51): those would start counting in currency here, so it keeps them out."""

        def any_posting(in_currency: bool) -> bool:
            return (
                self.conn.execute(
                    "SELECT 1 FROM postings WHERE (debit_account_id = ? OR credit_account_id = ?) "
                    "AND (currency_id IS NOT NULL) = ? LIMIT 1",
                    (account["id"], account["id"], int(in_currency)),
                ).fetchone()
                is not None
            )

        if account["currency"] == NO_CURRENCY and any_posting(in_currency=True):
            raise ValidationError(
                tr(
                    "счёт {code}: в проводках по счёту уже есть валюта другого счёта, "
                    "валютный учёт включить нельзя",
                    code=label,
                )
            )
        if mode == NO_CURRENCY and any_posting(in_currency=True):
            raise ValidationError(
                tr(
                    "счёт {code}: по счёту есть проводки в валюте, учёт только в манатах "
                    "невозможен",
                    code=label,
                )
            )
        if mode == CURRENCY_ONLY and any_posting(in_currency=False):
            raise ValidationError(
                tr(
                    "счёт {code}: по счёту есть проводки в манатах, учёт только в валюте "
                    "невозможен",
                    code=label,
                )
            )

    def set_account_role(self, company_id: int, role: str, account: int | str | None) -> None:
        """Which account automatic postings use for a role (ACCOUNT_ROLES); None clears it."""
        if role not in ACCOUNT_ROLES:
            raise ValidationError(tr("неизвестная роль счёта: {role}", role=role))
        with transaction(self.conn):
            self._company(company_id)
            if account is None:
                self.conn.execute(
                    "DELETE FROM account_roles WHERE company_id = ? AND role = ?",
                    (company_id, role),
                )
                self._audit(company_id, "account_role", 0, "clear", {"role": role})
                return
            acc = self._account(company_id, account)
            if acc["is_group"] or not acc["active"]:
                raise ValidationError(
                    tr("счёт {code}: нужен активный счёт проводок", code=account_label(acc))
                )
            self.conn.execute(
                "INSERT INTO account_roles (company_id, role, account_id) VALUES (?, ?, ?) "
                "ON CONFLICT (company_id, role) DO UPDATE SET account_id = excluded.account_id",
                (company_id, role, acc["id"]),
            )
            self._audit(
                company_id, "account_role", acc["id"], "set", {"role": role, "code": acc["code"]}
            )

    def account_role(self, company_id: int, role: str) -> int | None:
        """The account chosen for a role; if none is, the only active posting account of
        the role's type (several such accounts: the user has to choose)."""
        row = self.conn.execute(
            "SELECT account_id FROM account_roles WHERE company_id = ? AND role = ?",
            (company_id, role),
        ).fetchone()
        if row is not None:
            return row["account_id"]
        if role not in ROLE_TYPES:
            return None
        typed = self.conn.execute(
            "SELECT id FROM accounts WHERE company_id = ? AND account_type = ? "
            "AND is_group = 0 AND active = 1 LIMIT 2",
            (company_id, ROLE_TYPES[role]),
        ).fetchall()
        return typed[0]["id"] if len(typed) == 1 else None

    def _has_postings(self, account_id: int) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM postings "
                "WHERE debit_account_id = ? OR credit_account_id = ? LIMIT 1",
                (account_id, account_id),
            ).fetchone()
            is not None
        )
