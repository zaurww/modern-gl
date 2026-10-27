"""Account classes and types (D14, D35): what an account means, whatever its code."""

from __future__ import annotations

from modern_gl.application.ledger.base import LedgerBase, account_label
from modern_gl.domain.accounts import ACCOUNT_CLASSES, TYPE_CLASS
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class AccountTypeCommands(LedgerBase):
    """Use cases of an account's class and type: what it means, whatever its code."""

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
        were set differently on purpose. A type of another class is cleared.
        """
        with transaction(self.conn):
            acc = self._account(company_id, account)
            self._check_class(account_label(acc), account_class)
            old = acc["account_class"]
            ids = self._with_followers(company_id, acc["id"], "account_class IS ?", (old,))
            # one statement: the file refuses a type of another class even for a moment (0057)
            self.conn.executemany(
                "UPDATE accounts SET account_class = ?, "
                "account_type = CASE WHEN ? = 1 THEN NULL ELSE account_type END "
                "WHERE company_id = ? AND id = ?",
                [
                    (
                        account_class,
                        int(self._type_class(i) not in (None, account_class)),
                        company_id,
                        i,
                    )
                    for i in ids
                ],
            )
            if contra is not None:
                self.conn.execute(
                    "UPDATE accounts SET contra = ? WHERE company_id = ? AND id = ?",
                    (int(contra), company_id, acc["id"]),
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

    def set_account_type(
        self, company_id: int, account: int | str, account_type: str | None
    ) -> None:
        """Change an account's type; the class follows it (None clears the type and keeps
        the class). Audited. Subaccounts that had the account's type and class follow it."""
        with transaction(self.conn):
            acc = self._account(company_id, account)
            label = account_label(acc)
            account_class = self._class_of_type(label, account_type, None) or acc["account_class"]
            old = (acc["account_type"], acc["account_class"])
            ids = self._with_followers(
                company_id, acc["id"], "account_type IS ? AND account_class IS ?", old
            )
            self.conn.executemany(
                "UPDATE accounts SET account_type = ?, account_class = ? "
                "WHERE company_id = ? AND id = ?",
                [(account_type, account_class, company_id, i) for i in ids],
            )
            self._audit(
                company_id,
                "account",
                acc["id"],
                "set_type",
                {
                    "code": acc["code"],
                    "from": old[0],
                    "to": account_type,
                    "class": account_class,
                    "subaccounts": len(ids) - 1,
                },
            )

    def _with_followers(
        self, company_id: int, account_id: int, same: str, values: tuple
    ) -> list[int]:
        """The account and its subaccounts, at any depth, that are like it (`same` — an SQL
        condition): these follow a change of its class or type. A subaccount set otherwise
        on purpose stops the walk below it."""
        ids = [account_id]
        stack = [account_id]
        while stack:
            children = self.conn.execute(
                f"SELECT id FROM accounts WHERE company_id = ? AND parent_id = ? AND {same}",
                (company_id, stack.pop(), *values),
            ).fetchall()
            ids += [c["id"] for c in children]
            stack += [c["id"] for c in children]
        return ids

    def _type_class(self, account_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT account_type FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return TYPE_CLASS.get(row["account_type"])

    @staticmethod
    def _class_of_type(code: str, account_type: str | None, account_class: str | None):
        """The class a type gives (or `account_class` without a type); they must agree."""
        if account_type is None:
            return account_class
        if account_type not in TYPE_CLASS:
            raise ValidationError(
                tr("счёт {code}: неизвестный тип счёта {type}", code=code, type=account_type)
            )
        if account_class not in (None, TYPE_CLASS[account_type]):
            raise ValidationError(
                tr(
                    "счёт {code}: тип {type} не подходит к классу {cls}",
                    code=code,
                    type=account_type,
                    cls=account_class,
                )
            )
        return TYPE_CLASS[account_type]

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
