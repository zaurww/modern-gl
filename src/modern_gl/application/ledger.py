"""Write-side use cases: companies, chart of accounts, subconto, documents, posting.

All accounting rules live here (and are mirrored by DB constraints as defense in depth).
UI and importers call these methods; they never write ledger tables directly.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from modern_gl.domain import formula as formulas
from modern_gl.domain.accounts import ACCOUNT_CLASSES
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

DEFAULT_LAYERS = (
    ("common", "Общий учёт"),
    ("ifrs_adj", "Корректировки МСФО"),
    ("tax_adj", "Налоговые корректировки"),
)
MAX_SUBCONTO = 3
SIDES = (("debit", "dt"), ("credit", "ct"))


@dataclass(frozen=True)
class PostingInput:
    """One Dt/Ct pair. Subconto values are given per position (1..3) of each account."""

    debit_account_id: int
    credit_account_id: int
    amount: str | int | Decimal
    debit_subconto: Sequence[int | None] = ()
    credit_subconto: Sequence[int | None] = ()
    memo: str = ""


@dataclass(frozen=True)
class TemplateLine:
    """A line of an entry template. Anything left empty is filled in by hand."""

    debit_account_id: int | None = None
    credit_account_id: int | None = None
    formula: str = ""  # amount: S, S*18/118, S-L2… (see domain.formula); "" = by hand
    debit_subconto: Sequence[int | None] = ()
    credit_subconto: Sequence[int | None] = ()
    memo: str = ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pad(values: Sequence[int | None], line_no: int) -> list[int | None]:
    if len(values) > MAX_SUBCONTO:
        raise ValidationError(
            tr("строка {line}: больше {n} субконто", line=line_no, n=MAX_SUBCONTO)
        )
    return [*values, *([None] * (MAX_SUBCONTO - len(values)))]


def _code(code: str | None) -> str | None:
    """Account codes are optional: blank means no code."""
    return (code or "").strip() or None


def _label(account: sqlite3.Row) -> str:
    """How an account is named in messages: its code, or its name if it has none."""
    return account["code"] or account["name"]


class Ledger:
    def __init__(self, conn: sqlite3.Connection, actor: str = "local") -> None:
        self.conn = conn
        self.actor = actor

    # ---- companies -------------------------------------------------------------------

    def create_company(self, name: str, base_currency: str = "AZN") -> int:
        with transaction(self.conn):
            company_id = self.conn.execute(
                "INSERT INTO companies (name, base_currency, created_at) VALUES (?, ?, ?)",
                (name, base_currency, _now()),
            ).lastrowid
            self.conn.executemany(
                "INSERT INTO layers (company_id, code, name) VALUES (?, ?, ?)",
                [(company_id, code, tr(title)) for code, title in DEFAULT_LAYERS],
            )
            self._audit(
                company_id,
                "company",
                company_id,
                "create",
                {"name": name, "base_currency": base_currency},
            )
        return company_id

    def set_closed_through(self, company_id: int, through: date | str | None) -> None:
        """Close the period up to `through` inclusive; None reopens everything. Audited."""
        value = None if through is None else iso_date(through)
        with transaction(self.conn):
            old = self._company(company_id)["closed_through"]
            self.conn.execute(
                "UPDATE companies SET closed_through = ? WHERE id = ?", (value, company_id)
            )
            self._audit(
                company_id, "company", company_id, "set_closed_through", {"from": old, "to": value}
            )

    # ---- subconto --------------------------------------------------------------------

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
            kind_id = self.conn.execute(
                "INSERT INTO subconto_kinds (company_id, code, name) VALUES (?, ?, ?)",
                (company_id, code, name),
            ).lastrowid
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
                value_id = self.conn.execute(
                    "INSERT INTO subconto_values (company_id, kind_id, code, name) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, kind_id, code, name),
                ).lastrowid
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

    def _subconto_value(self, company_id: int, value_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM subconto_values WHERE company_id = ? AND id = ?", (company_id, value_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("элемент справочника не найден"))
        return row

    # ---- chart of accounts -----------------------------------------------------------

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
    ) -> int:
        """Add an account. `subconto` lists subconto kind ids for positions 1..3.

        The code is optional (empty: the account is known by its name). `parent` is the
        parent account's id or code. Without `account_class` the account inherits its
        parent's class (or stays unclassified). `two_sided` (balance may be on either
        side, shown expanded per first subconto) is inherited from the parent unless given.
        """
        code = _code(code)
        name = name.strip()
        label = code or name
        if not name:
            raise ValidationError(tr("название счёта не может быть пустым"))
        self._check_class(label, account_class)
        if is_group and subconto:
            raise ValidationError(tr("счёт {code}: у группы не бывает субконто", code=label))
        sc = _pad(subconto, 0)
        with transaction(self.conn):
            parent_id = None
            if parent is not None:
                parent_row = self._account(company_id, parent)
                if not parent_row["is_group"]:
                    raise ValidationError(
                        tr(
                            "счёт {code}: родитель {parent} не группа",
                            code=label,
                            parent=_label(parent_row),
                        )
                    )
                parent_id = parent_row["id"]
                account_class = account_class or parent_row["account_class"]
                if two_sided is None:
                    two_sided = bool(parent_row["two_sided"])
            try:
                account_id = self.conn.execute(
                    "INSERT INTO accounts (company_id, code, name, parent_id, is_group, "
                    "sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra, two_sided) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
                ).lastrowid
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
                {"code": code, "name": name, "class": account_class, "two_sided": bool(two_sided)},
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
            self._check_class(_label(acc), account_class)
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
    ) -> None:
        """Rename / re-code / reconfigure an account (given by id or code). Audited.

        `new_code=""` removes the code. History is protected: an account with postings
        cannot become a group and its subconto kinds cannot change (old postings carry
        values of those kinds). Codes are only labels — postings reference the account
        id, so re-coding is safe.
        """
        with transaction(self.conn):
            acc = self._account(company_id, account)
            label = _label(acc)
            new_code = acc["code"] if new_code is None else _code(new_code)
            name = acc["name"] if name is None else name.strip()
            two_sided = bool(acc["two_sided"]) if two_sided is None else bool(two_sided)
            group = bool(acc["is_group"]) if is_group is None else bool(is_group)
            current_sc = [acc["sc1_kind_id"], acc["sc2_kind_id"], acc["sc3_kind_id"]]
            sc = current_sc if subconto is None else _pad(list(subconto), 0)
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
                sc = [None, None, None]
            if sc != current_sc and used:
                raise ValidationError(
                    tr("счёт {code}: по счёту есть проводки, субконто менять нельзя", code=label)
                )
            try:
                self.conn.execute(
                    "UPDATE accounts SET code = ?, name = ?, two_sided = ?, is_group = ?, "
                    "sc1_kind_id = ?, sc2_kind_id = ?, sc3_kind_id = ? WHERE id = ?",
                    (new_code, name, int(two_sided), int(group), *sc, acc["id"]),
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
                    },
                    "after": {
                        "code": new_code,
                        "name": name,
                        "two_sided": two_sided,
                        "group": group,
                        "subconto": sc,
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

    # ---- entry templates -------------------------------------------------------------

    def save_template(
        self,
        company_id: int,
        name: str,
        lines: Sequence[TemplateLine],
        memo: str = "",
        template_id: int | None = None,
    ) -> int:
        """Create an entry template, or replace one (name, memo and all lines). Audited."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название шаблона не может быть пустым"))
        lines = [ln for ln in lines if ln.debit_account_id or ln.credit_account_id or ln.formula]
        if not lines:
            raise ValidationError(tr("в шаблоне нет строк"))
        formulas.check([ln.formula for ln in lines])
        with transaction(self.conn):
            if template_id is None:
                template_id = self.conn.execute(
                    "INSERT INTO entry_templates (company_id, name, memo) VALUES (?, ?, ?)",
                    (company_id, name, memo.strip()),
                ).lastrowid
                action = "create"
            else:
                found = self.conn.execute(
                    "UPDATE entry_templates SET name = ?, memo = ? WHERE company_id = ? AND id = ?",
                    (name, memo.strip(), company_id, template_id),
                ).rowcount
                if not found:
                    raise NotFoundError(tr("шаблон не найден"))
                self.conn.execute(
                    "DELETE FROM entry_template_lines WHERE template_id = ?", (template_id,)
                )
                action = "update"
            for line_no, ln in enumerate(lines, start=1):
                self.conn.execute(
                    "INSERT INTO entry_template_lines (company_id, template_id, line_no, "
                    "debit_account_id, credit_account_id, dt_sc1, dt_sc2, dt_sc3, "
                    "ct_sc1, ct_sc2, ct_sc3, formula, memo) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        company_id,
                        template_id,
                        line_no,
                        ln.debit_account_id,
                        ln.credit_account_id,
                        *_pad(ln.debit_subconto, line_no),
                        *_pad(ln.credit_subconto, line_no),
                        ln.formula.strip(),
                        ln.memo.strip(),
                    ),
                )
            self._audit(
                company_id,
                "entry_template",
                template_id,
                action,
                {"name": name, "lines": [ln.formula for ln in lines]},
            )
        return template_id

    def delete_template(self, company_id: int, template_id: int) -> None:
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT name FROM entry_templates WHERE company_id = ? AND id = ?",
                (company_id, template_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(tr("шаблон не найден"))
            self.conn.execute("DELETE FROM entry_templates WHERE id = ?", (template_id,))
            self._audit(company_id, "entry_template", template_id, "delete", {"name": row[0]})

    # ---- documents -------------------------------------------------------------------

    def create_draft(
        self,
        company_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str = "",
        layer: str = "common",
    ) -> int:
        with transaction(self.conn):
            doc_id = self._insert_document(company_id, doc_date, memo, layer)
            self._insert_postings(company_id, doc_id, postings)
            self._audit(company_id, "document", doc_id, "create_draft", {})
        return doc_id

    def update_draft(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str = "",
        layer: str = "common",
    ) -> None:
        with transaction(self.conn):
            self._require_draft(self._document(company_id, doc_id))
            self.conn.execute(
                "UPDATE documents SET doc_date = ?, memo = ?, layer_id = ? WHERE id = ?",
                (iso_date(doc_date), memo, self._layer_id(company_id, layer), doc_id),
            )
            self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc_id,))
            self._insert_postings(company_id, doc_id, postings)
            self._audit(company_id, "document", doc_id, "update_draft", {})

    def delete_draft(self, company_id: int, doc_id: int) -> None:
        with transaction(self.conn):
            self._require_draft(self._document(company_id, doc_id))
            self.delete_document(company_id, doc_id)

    def unpost(self, company_id: int, doc_id: int) -> None:
        """Turn a posted document back into an editable draft (open period only).

        The audit trail keeps the full posted content. A red-storno document cannot be
        unposted — delete it instead; a reversed document needs its storno deleted first.
        """
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            self._require_not_inventory_document(doc_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("документ №{n} не проведён", n=doc["number"]))
            if doc["reversal_of"] is not None:
                raise ValidationError(
                    tr("сторно №{n} нельзя распровести, его можно только удалить", n=doc["number"])
                )
            self._require_changeable(company_id, doc)
            snapshot = self._snapshot(doc)
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?", (doc_id,)
            )
            self._audit(company_id, "document", doc_id, "unpost", snapshot)

    def delete_document(self, company_id: int, doc_id: int) -> None:
        """Delete a draft, or a posted document in an open period. Audited with its content.

        Deleting a storno brings the reversed document back to normal.
        """
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            self._require_not_inventory_document(doc_id)
            if doc["status"] == "posted":
                self._require_changeable(company_id, doc)
            snapshot = self._snapshot(doc)
            if doc["status"] == "posted":  # immutability triggers allow only this path
                self.conn.execute(
                    "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?",
                    (doc_id,),
                )
            self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            self._audit(company_id, "document", doc_id, "delete", snapshot)

    def _require_changeable(self, company_id: int, doc: sqlite3.Row) -> None:
        closed = self._company(company_id)["closed_through"]
        if closed is not None and doc["doc_date"] <= closed:
            raise PeriodClosedError(
                tr(
                    "документ №{number} от {date}: период закрыт по {closed}",
                    number=doc["number"],
                    date=doc["doc_date"],
                    closed=closed,
                )
                + ". "
                + tr("Исправьте его сторно в открытом периоде.")
            )
        storno = self.conn.execute(
            "SELECT number FROM documents WHERE reversal_of = ?", (doc["id"],)
        ).fetchone()
        if storno is not None:
            raise ValidationError(
                tr(
                    "документ №{n} сторнирован документом №{m}: сначала удалите сторно",
                    n=doc["number"],
                    m=storno["number"],
                )
            )

    def _require_not_inventory_document(self, doc_id: int) -> None:
        linked = self.conn.execute(
            "SELECT number FROM inventory_documents WHERE gl_document_id = ?", (doc_id,)
        ).fetchone()
        if linked is not None:
            raise ValidationError(
                tr(
                    "бухгалтерский документ создан складским документом №{n}; "
                    "исправьте его через склад",
                    n=linked["number"],
                )
            )

    def _snapshot(self, doc: sqlite3.Row) -> dict:
        """Everything needed to see later what a removed / unposted document contained."""
        postings = [
            {k: p[k] for k in p.keys() if k not in ("id", "company_id", "document_id")}
            for p in self.conn.execute(
                "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (doc["id"],)
            )
        ]
        header = {
            k: doc[k]
            for k in ("number", "doc_date", "memo", "status", "layer", "reversal_of", "posted_at")
        }
        return {**header, "postings": postings}

    def post(self, company_id: int, doc_id: int) -> None:
        with transaction(self.conn):
            self._post(company_id, doc_id)

    def post_new(
        self,
        company_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str = "",
        layer: str = "common",
    ) -> int:
        """Create and post a document in one atomic step."""
        with transaction(self.conn):
            doc_id = self._insert_document(company_id, doc_date, memo, layer)
            self._insert_postings(company_id, doc_id, postings)
            self._post(company_id, doc_id)
        return doc_id

    def reverse(
        self, company_id: int, doc_id: int, doc_date: date | str, memo: str | None = None
    ) -> int:
        """Red storno: a new posted document with the same postings and negated amounts."""
        with transaction(self.conn):
            orig = self._document(company_id, doc_id)
            self._require_not_inventory_document(doc_id)
            if orig["status"] != "posted":
                raise ValidationError(tr("документ №{n} не проведён", n=orig["number"]))
            if orig["reversal_of"] is not None:
                raise ValidationError(tr("документ №{n} сам является сторно", n=orig["number"]))
            if self.conn.execute(
                "SELECT 1 FROM documents WHERE reversal_of = ?", (doc_id,)
            ).fetchone():
                raise ValidationError(tr("документ №{n} уже сторнирован", n=orig["number"]))
            new_id = self._insert_document(
                company_id,
                doc_date,
                memo if memo is not None else tr("Сторно документа №{n}", n=orig["number"]),
                orig["layer"],
                reversal_of=doc_id,
            )
            self.conn.execute(
                """
                INSERT INTO postings (company_id, document_id, line_no, debit_account_id,
                    credit_account_id, amount, dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo)
                SELECT company_id, ?, line_no, debit_account_id, credit_account_id, -amount,
                    dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo
                FROM postings WHERE document_id = ? ORDER BY line_no
                """,
                (new_id, doc_id),
            )
            self._post(company_id, new_id)
        return new_id

    # ---- internals (must run inside a transaction) -----------------------------------

    def _insert_document(
        self,
        company_id: int,
        doc_date: date | str,
        memo: str,
        layer: str,
        reversal_of: int | None = None,
    ) -> int:
        self._company(company_id)
        number = self.conn.execute(  # a counter, so numbers are never reused after deletion
            "UPDATE companies SET last_number = last_number + 1 WHERE id = ? RETURNING last_number",
            (company_id,),
        ).fetchone()[0]
        return self.conn.execute(
            "INSERT INTO documents (company_id, number, doc_date, memo, status, layer_id, "
            "reversal_of, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (
                company_id,
                number,
                iso_date(doc_date),
                memo,
                self._layer_id(company_id, layer),
                reversal_of,
                _now(),
            ),
        ).lastrowid

    def _insert_postings(
        self, company_id: int, doc_id: int, postings: Sequence[PostingInput]
    ) -> None:
        rows = []
        for line_no, p in enumerate(postings, start=1):
            try:
                amount = to_minor(p.amount)
            except (TypeError, ValueError) as e:
                raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
            if amount == 0:
                raise ValidationError(tr("строка {line}: нулевая сумма", line=line_no))
            rows.append(
                (
                    company_id,
                    doc_id,
                    line_no,
                    p.debit_account_id,
                    p.credit_account_id,
                    amount,
                    *_pad(p.debit_subconto, line_no),
                    *_pad(p.credit_subconto, line_no),
                    p.memo,
                )
            )
        try:
            self.conn.executemany(
                "INSERT INTO postings (company_id, document_id, line_no, debit_account_id, "
                "credit_account_id, amount, dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        except sqlite3.IntegrityError as e:
            raise ValidationError(
                tr("счёт или субконто не существует или принадлежит другой компании")
            ) from e

    def _post(self, company_id: int, doc_id: int) -> None:
        doc = self._document(company_id, doc_id)
        self._require_draft(doc)
        self._validate_for_posting(company_id, doc)
        self.conn.execute(
            "UPDATE documents SET status = 'posted', posted_at = ? WHERE id = ?", (_now(), doc_id)
        )
        action = "reverse" if doc["reversal_of"] is not None else "post"
        self._audit(
            company_id,
            "document",
            doc_id,
            action,
            {"number": doc["number"], "reversal_of": doc["reversal_of"]},
        )

    def _validate_for_posting(self, company_id: int, doc: sqlite3.Row) -> None:
        closed = self._company(company_id)["closed_through"]
        if closed is not None and doc["doc_date"] <= closed:
            raise PeriodClosedError(
                tr(
                    "документ №{number} от {date}: период закрыт по {closed}",
                    number=doc["number"],
                    date=doc["doc_date"],
                    closed=closed,
                )
            )
        postings = self.conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (doc["id"],)
        ).fetchall()
        if not postings:
            raise ValidationError(tr("документ №{n} без проводок", n=doc["number"]))

        account_ids = {p[f"{side}_account_id"] for p in postings for side, _ in SIDES}
        accounts = {
            r["id"]: r
            for r in self.conn.execute(
                f"SELECT * FROM accounts WHERE id IN ({','.join('?' * len(account_ids))})",
                tuple(account_ids),
            )
        }
        value_ids = {
            p[f"{prefix}_sc{i}"]
            for p in postings
            for _, prefix in SIDES
            for i in range(1, MAX_SUBCONTO + 1)
        } - {None}
        values = (
            {
                r["id"]: r
                for r in self.conn.execute(
                    f"SELECT * FROM subconto_values WHERE id IN ({','.join('?' * len(value_ids))})",
                    tuple(value_ids),
                )
            }
            if value_ids
            else {}
        )

        is_reversal = doc["reversal_of"] is not None
        for p in postings:
            line = p["line_no"]
            if is_reversal and p["amount"] >= 0:
                raise ValidationError(
                    tr("строка {line}: сумма сторно должна быть отрицательной", line=line)
                )
            if not is_reversal and p["amount"] <= 0:
                raise ValidationError(
                    tr("строка {line}: сумма должна быть положительной", line=line)
                )
            for side, prefix in SIDES:
                acc = accounts[p[f"{side}_account_id"]]
                label = tr(
                    "строка {line}, {side} {code}",
                    line=line,
                    side=tr("Дт" if side == "debit" else "Кт"),
                    code=_label(acc),
                )
                if acc["is_group"]:
                    raise ValidationError(
                        tr("{label}: нельзя проводить на группу счетов", label=label)
                    )
                if not acc["active"] and not is_reversal:
                    raise ValidationError(tr("{label}: счёт не активен", label=label))
                for i in range(1, MAX_SUBCONTO + 1):
                    kind_id = acc[f"sc{i}_kind_id"]
                    value_id = p[f"{prefix}_sc{i}"]
                    if kind_id is None:
                        if value_id is not None:
                            raise ValidationError(
                                tr("{label}: у счёта нет субконто {i}", label=label, i=i)
                            )
                        continue
                    if value_id is None:
                        raise ValidationError(
                            tr("{label}: не заполнено субконто {i}", label=label, i=i)
                        )
                    if values[value_id]["kind_id"] != kind_id:
                        raise ValidationError(
                            tr("{label}: субконто {i} не того вида", label=label, i=i)
                        )

    def _require_draft(self, doc: sqlite3.Row) -> None:
        if doc["status"] != "draft":
            raise ValidationError(tr("документ №{n} уже проведён и не изменяется", n=doc["number"]))

    def _company(self, company_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise NotFoundError(tr("компания {id} не найдена", id=company_id))
        return row

    def _document(self, company_id: int, doc_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT d.*, l.code AS layer FROM documents d JOIN layers l ON l.id = d.layer_id "
            "WHERE d.company_id = ? AND d.id = ?",
            (company_id, doc_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("документ {id} не найден", id=doc_id))
        return row

    def _account(self, company_id: int, account: int | str) -> sqlite3.Row:
        """An account by id (int) or by code (str)."""
        column = "id" if isinstance(account, int) else "code"
        row = self.conn.execute(
            f"SELECT * FROM accounts WHERE company_id = ? AND {column} = ?",
            (company_id, account),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("счёт {code} не найден", code=account))
        return row

    def _layer_id(self, company_id: int, code: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM layers WHERE company_id = ? AND code = ?", (company_id, code)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("слой {code} не найден", code=code))
        return row["id"]

    def _audit(
        self, company_id: int | None, entity: str, entity_id: int, action: str, details: dict
    ) -> None:
        self.conn.execute(
            "INSERT INTO audit_events (company_id, at, actor, entity, entity_id, action, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                _now(),
                self.actor,
                entity,
                entity_id,
                action,
                json.dumps(details, ensure_ascii=False),
            ),
        )
