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
ACCOUNT_KINDS = ("A", "P", "AP")
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pad(values: Sequence[int | None], line_no: int) -> list[int | None]:
    if len(values) > MAX_SUBCONTO:
        raise ValidationError(
            tr("строка {line}: больше {n} субконто", line=line_no, n=MAX_SUBCONTO)
        )
    return [*values, *([None] * (MAX_SUBCONTO - len(values)))]


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

    def add_subconto_kind(self, company_id: int, code: str, name: str) -> int:
        with transaction(self.conn):
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

    # ---- chart of accounts -----------------------------------------------------------

    def add_account(
        self,
        company_id: int,
        code: str,
        name: str,
        *,
        kind: str = "AP",
        parent_code: str | None = None,
        is_group: bool = False,
        subconto: Sequence[int] = (),
    ) -> int:
        """Add an account. `subconto` lists subconto kind ids for positions 1..3."""
        if kind not in ACCOUNT_KINDS:
            raise ValidationError(
                tr("счёт {code}: вид должен быть одним из {kinds}", code=code, kinds=ACCOUNT_KINDS)
            )
        if is_group and subconto:
            raise ValidationError(tr("счёт {code}: у группы не бывает субконто", code=code))
        sc = _pad(subconto, 0)
        with transaction(self.conn):
            parent_id = None
            if parent_code is not None:
                parent = self._account_by_code(company_id, parent_code)
                if not parent["is_group"]:
                    raise ValidationError(
                        tr(
                            "счёт {code}: родитель {parent} не группа",
                            code=code,
                            parent=parent_code,
                        )
                    )
                parent_id = parent["id"]
            try:
                account_id = self.conn.execute(
                    "INSERT INTO accounts (company_id, code, name, parent_id, kind, is_group, "
                    "sc1_kind_id, sc2_kind_id, sc3_kind_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (company_id, code, name, parent_id, kind, int(is_group), *sc),
                ).lastrowid
            except sqlite3.IntegrityError as e:
                raise ValidationError(
                    tr("не удалось добавить счёт {code}: {error}", code=code, error=e)
                ) from e
            self._audit(
                company_id,
                "account",
                account_id,
                "create",
                {"code": code, "name": name, "kind": kind},
            )
        return account_id

    def account_id(self, company_id: int, code: str) -> int:
        return self._account_by_code(company_id, code)["id"]

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
            doc = self._document(company_id, doc_id)
            self._require_draft(doc)
            self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            self._audit(company_id, "document", doc_id, "delete_draft", {"number": doc["number"]})

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
        number = self.conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM documents WHERE company_id = ?",
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
                    code=acc["code"],
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

    def _account_by_code(self, company_id: int, code: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? AND code = ?", (company_id, code)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("счёт {code} не найден", code=code))
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
