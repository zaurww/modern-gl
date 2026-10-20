"""The chart of accounts."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from modern_gl.application.common import insert, pad_subconto
from modern_gl.application.ledger.base import LedgerBase, account_label, clean_code
from modern_gl.domain.accounts import ACCOUNT_CLASSES
from modern_gl.domain.currency import CURRENCY_ONLY, NO_CURRENCY, currency_mode
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class ChartCommands(LedgerBase):
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
        contra: bool = False,
        two_sided: bool | None = None,
        currency: bool | int | None = None,
    ) -> int:
        """Add an account. `subconto` lists subconto kind ids for positions 1..3.

        The code is optional (empty: the account is known by its name). `parent` is the
        parent account's id or code. Without `account_class` the account inherits its
        parent's class (or stays unclassified). `two_sided` (balance may be on either
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
        if is_group and subconto:
            raise ValidationError(tr("счёт {code}: у группы не бывает субконто", code=label))
        sc = pad_subconto(subconto)
        with transaction(self.conn):
            parent_id = None
            if parent is not None:
                parent_row = self._account(company_id, parent)
                if not parent_row["is_group"]:
                    raise ValidationError(
                        tr(
                            "счёт {code}: родитель {parent} не группа",
                            code=label,
                            parent=account_label(parent_row),
                        )
                    )
                parent_id = parent_row["id"]
                account_class = account_class or parent_row["account_class"]
                if two_sided is None:
                    two_sided = bool(parent_row["two_sided"])
                if currency is None:
                    currency = parent_row["currency"]
            mode = currency_mode(currency or NO_CURRENCY)
            try:
                account_id = insert(
                    self.conn,
                    "INSERT INTO accounts (company_id, code, name, parent_id, is_group, "
                    "sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra, two_sided, "
                    "currency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        company_id,
                        code,
                        name,
                        parent_id,
                        int(is_group),
                        *sc,
                        account_class,
                        int(contra),
                        int(bool(two_sided)),
                        mode,
                    ),
                )
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e):
                    raise ValidationError(tr("счёт {code} уже есть", code=label)) from e
                raise ValidationError(
                    tr("не удалось добавить счёт {code}: {error}", code=label, error=e)
                ) from e
            self._audit(
                company_id,
                "account",
                account_id,
                "create",
                {
                    "code": code,
                    "name": name,
                    "class": account_class,
                    "two_sided": bool(two_sided),
                    "currency": mode,
                },
            )
        return account_id

    def account_id(self, company_id: int, code: str) -> int:
        return self._account(company_id, code)["id"]

    def set_account_class(
        self,
        company_id: int,
        account: int | str,
        account_class: str | None,
        contra: bool | None = None,
    ) -> None:
        """Change an account's class (and optionally its contra flag). Audited.

        `account` is the account id or code. Subaccounts that had the same class as the
        account follow it, so changing a group re-classifies its subaccounts unless they
        were set differently on purpose.
        """
        with transaction(self.conn):
            acc = self._account(company_id, account)
            self._check_class(account_label(acc), account_class)
            old = acc["account_class"]
            ids = [acc["id"]]
            stack = [acc["id"]]
            while stack:
                children = self.conn.execute(
                    "SELECT id FROM accounts WHERE company_id = ? AND parent_id = ? "
                    "AND account_class IS ?",
                    (company_id, stack.pop(), old),
                ).fetchall()
                ids += [c["id"] for c in children]
                stack += [c["id"] for c in children]
            self.conn.executemany(
                "UPDATE accounts SET account_class = ? WHERE id = ?",
                [(account_class, i) for i in ids],
            )
            if contra is not None:
                self.conn.execute(
                    "UPDATE accounts SET contra = ? WHERE id = ?", (int(contra), acc["id"])
                )
            self._audit(
                company_id,
                "account",
                acc["id"],
                "set_class",
                {
                    "code": acc["code"],
                    "from": old,
                    "to": account_class,
                    "contra": contra,
                    "subaccounts": len(ids) - 1,
                },
            )

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
        values of those kinds). Currency accounting changes only as far as the old postings
        fit: "in manat or in a currency" always does; "manat only" needs no posting in a
        currency, "currency only" none in manat. Codes are
        only labels — postings reference the account id, so re-coding is safe.
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
                        "SELECT 1 FROM accounts WHERE parent_id = ?", (acc["id"],)
                    ).fetchone()
                ):
                    raise ValidationError(tr("счёт {code}: у группы есть субсчета", code=label))
            if group:
                sc = (None, None, None)
            if sc != current_sc and used:
                raise ValidationError(
                    tr("счёт {code}: по счёту есть проводки, субконто менять нельзя", code=label)
                )
            if mode != acc["currency"] and used:
                self._check_currency_fits(acc, label, mode)
            try:
                self.conn.execute(
                    "UPDATE accounts SET code = ?, name = ?, two_sided = ?, is_group = ?, "
                    "sc1_kind_id = ?, sc2_kind_id = ?, sc3_kind_id = ?, currency = ? WHERE id = ?",
                    (new_code, name, int(two_sided), int(group), *sc, mode, acc["id"]),
                )
            except sqlite3.IntegrityError as e:
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

    def _check_currency_fits(self, account: sqlite3.Row, label: str, mode: int) -> None:
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

    def _has_postings(self, account_id: int) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM postings "
                "WHERE debit_account_id = ? OR credit_account_id = ? LIMIT 1",
                (account_id, account_id),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _check_class(code: str, account_class: str | None) -> None:
        if account_class is not None and account_class not in ACCOUNT_CLASSES:
            raise ValidationError(
                tr(
                    "счёт {code}: класс должен быть одним из {classes}",
                    code=code,
                    classes=ACCOUNT_CLASSES,
                )
            )
