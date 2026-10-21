"""Documents: drafts, posting, corrections, import and currency revaluation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal

from modern_gl.application.common import MAX_SUBCONTO, insert, now, pad_subconto
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.inputs import SIDES, ImportedDocument, ImportOutcome, PostingInput
from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.application.queries import is_opening_document
from modern_gl.domain.accounts import OPENING_BALANCE
from modern_gl.domain.currency import CURRENCY_OPTIONAL, to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError, NotFoundError, PeriodClosedError, ValidationError
from modern_gl.domain.invoice import KINDS, normalize_invoice
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class _Discard(Exception):
    """Rolls back an import that had problems or was only a check."""


class DocumentCommands(SubcontoCommands):
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
            self._require_not_module_document(doc_id)
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

    def repost(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str = "",
        layer: str = "common",
    ) -> None:
        """Edit a posted document in place, as in 1C: the new content is posted atomically
        and keeps the number; the audit trail keeps the old content."""
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            self._require_not_module_document(doc_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("документ №{n} не проведён", n=doc["number"]))
            if doc["reversal_of"] is not None:
                raise ValidationError(
                    tr("сторно №{n} нельзя изменить, его можно только удалить", n=doc["number"])
                )
            self._require_changeable(company_id, doc)
            snapshot = self._snapshot(doc)
            self._rewrite(company_id, doc_id, doc_date, postings, memo, layer)
            self._audit(company_id, "document", doc_id, "repost", snapshot)

    def rewrite_linked(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str = "",
    ) -> None:
        """Replace the postings of a document a module (the warehouse) created, keeping its
        number. Only the module calls this; the journal refuses to touch such documents."""
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            if doc["status"] == "posted" and self._same_content(doc, doc_date, postings, memo):
                return  # a recalculation that changed nothing leaves no trace
            self._require_changeable(company_id, doc)
            snapshot = self._snapshot(doc)
            self._rewrite(company_id, doc_id, doc_date, postings, memo, doc["layer"])
            self._audit(company_id, "document", doc_id, "repost", snapshot)

    def _same_content(
        self,
        doc: sqlite3.Row,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> bool:
        if doc["doc_date"] != iso_date(doc_date) or doc["memo"] != memo:
            return False
        stored = [
            (
                p["debit_account_id"],
                p["credit_account_id"],
                p["amount"],
                (p["dt_sc1"], p["dt_sc2"], p["dt_sc3"]),
                (p["ct_sc1"], p["ct_sc2"], p["ct_sc3"]),
                p["memo"],
                p["currency_id"],
                p["currency_amount"],
                p["invoice"],
                p["invoice_kind"],
            )
            for p in self.conn.execute(
                "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (doc["id"],)
            )
        ]
        try:
            wanted = [
                (
                    p.debit_account_id,
                    p.credit_account_id,
                    to_minor(p.amount),
                    pad_subconto(p.debit_subconto),
                    pad_subconto(p.credit_subconto),
                    p.memo,
                    p.currency_id,
                    None if p.currency_id is None else to_minor(p.currency_amount or 0),
                    normalize_invoice(p.invoice),
                    _invoice_kind(p),
                )
                for p in postings
            ]
        except (TypeError, ValueError, ValidationError):
            return False
        return stored == wanted

    def _rewrite(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
        layer: str,
    ) -> None:
        # immutability triggers let a posted document change only by becoming a draft first
        self.conn.execute(
            "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?", (doc_id,)
        )
        self.conn.execute(
            "UPDATE documents SET doc_date = ?, memo = ?, layer_id = ? WHERE id = ?",
            (iso_date(doc_date), memo, self._layer_id(company_id, layer), doc_id),
        )
        self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc_id,))
        self._insert_postings(company_id, doc_id, postings)
        self._post(company_id, doc_id)

    def delete_document(self, company_id: int, doc_id: int) -> None:
        """Delete a draft, or a posted document in an open period. Audited with its content.

        Deleting a storno brings the reversed document back to normal.
        """
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            self._require_not_module_document(doc_id)
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
        landed = self.conn.execute(
            "SELECT d.number FROM landed_cost_charges c "
            "JOIN inventory_documents d ON d.id = c.document_id "
            "WHERE c.source_document_id = ? ORDER BY d.number LIMIT 1",
            (doc["id"],),
        ).fetchone()
        if landed is not None:
            raise ValidationError(
                tr(
                    "документ №{n} взят как расход партии в складском документе №{m}: "
                    "сначала уберите его оттуда",
                    n=doc["number"],
                    m=landed["number"],
                )
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

    def _require_not_module_document(self, doc_id: int) -> None:
        """Postings a module made (warehouse, currency conversion, bank) are corrected there."""
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
        if self.conn.execute(
            "SELECT 1 FROM currency_conversions WHERE document_id = ? OR credit_document_id = ?",
            (doc_id, doc_id),
        ).fetchone():
            raise ValidationError(
                tr("проводки созданы документом «Конвертация валюты»; исправьте его там")
            )
        if self.conn.execute(
            "SELECT 1 FROM bank_operations WHERE document_id = ?", (doc_id,)
        ).fetchone():
            raise ValidationError(
                tr("проводки созданы банковской операцией; исправьте её в разделе «Банк»")
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
            self._require_not_module_document(doc_id)
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
                    credit_account_id, amount, dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo,
                    currency_id, currency_amount, invoice, invoice_kind)
                SELECT company_id, ?, line_no, debit_account_id, credit_account_id, -amount,
                    dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo,
                    currency_id, -currency_amount, invoice, invoice_kind
                FROM postings WHERE document_id = ? ORDER BY line_no
                """,
                (new_id, doc_id),
            )
            self._post(company_id, new_id)
        return new_id

    def import_documents(
        self,
        company_id: int,
        documents: Sequence[ImportedDocument],
        new_values: Sequence[tuple[int, str, int | None]] = (),
        post: bool = True,
        check_only: bool = False,
    ) -> ImportOutcome:
        """Create many documents at once (import from Excel): all or nothing.

        `new_values` are (kind id, name, owner) directory elements to add first; a posting
        refers to the i-th of them by the subconto id -(i + 1), and so may the owner (a new
        contract of a new counterparty). Every document is checked on its
        own (a savepoint each), so all problems are reported, not only the first. With any
        problem, or with `check_only`, nothing is kept.
        """
        outcome = ImportOutcome()
        try:
            with transaction(self.conn):
                created: list[int] = []
                for kind_id, name, owner in new_values:
                    if owner is not None and owner < 0:
                        owner = created[-owner - 1]
                    created.append(
                        self.add_subconto_value(company_id, kind_id, name, owner_id=owner)
                    )

                def real(values: Sequence[int | None]) -> tuple[int | None, ...]:
                    return tuple(created[-v - 1] if v is not None and v < 0 else v for v in values)

                for index, doc in enumerate(documents):
                    postings = [
                        replace(
                            p,
                            debit_subconto=real(p.debit_subconto),
                            credit_subconto=real(p.credit_subconto),
                        )
                        for p in doc.postings
                    ]
                    self.conn.execute("SAVEPOINT import_document")
                    try:
                        create = self.post_new if post else self.create_draft
                        outcome.ids.append(
                            create(company_id, doc.doc_date, postings, doc.memo, doc.layer)
                        )
                    except LedgerError as e:
                        self.conn.execute("ROLLBACK TO import_document")
                        outcome.errors.append((index, str(e)))
                    self.conn.execute("RELEASE import_document")
                if outcome.errors or check_only:
                    raise _Discard
        except _Discard:
            outcome.ids = []
        return outcome

    def revalue(
        self,
        company_id: int,
        day: date | str,
        gain_account: int | str,
        loss_account: int | str | None = None,
        memo: str | None = None,
    ) -> int | None:
        """Переоценка валютных остатков on `day` (common layer).

        Every balance of a currency account — per subconto values and currency — is
        brought to its currency balance at the rate of the day. A gain is credited to
        `gain_account`, a loss debited to `loss_account` (the same account by default).
        Returns the posted document, or None when everything is already at the rate.
        """
        day = iso_date(day)
        with transaction(self.conn):
            gain = self._account(company_id, gain_account)
            loss = self._account(company_id, loss_account or gain_account)
            for acc in (gain, loss):
                if acc["currency"]:
                    raise ValidationError(
                        tr(
                            "счёт {code}: курсовые разницы относят на счёт без валютного учёта",
                            code=account_label(acc),
                        )
                    )
            postings = []
            for b in self._currency_balances(company_id, day):
                rate = rate_on(self.conn, company_id, b["currency_id"], day)
                if rate is None:
                    raise ValidationError(
                        tr("нет курса {code} на {date}", code=b["code"], date=day)
                    )
                diff = to_base(b["currency_balance"], rate.per_unit) - b["balance"]
                if diff == 0:
                    continue
                sc = (b["sc1"], b["sc2"], b["sc3"])
                if diff > 0:
                    dt, ct, dt_sc, ct_sc = b["account_id"], gain["id"], sc, ()
                else:
                    dt, ct, dt_sc, ct_sc = loss["id"], b["account_id"], (), sc
                postings.append(
                    PostingInput(
                        dt,
                        ct,
                        Decimal(abs(diff)).scaleb(-2),
                        dt_sc,
                        ct_sc,
                        tr("Курсовая разница {code}", code=b["code"]),
                        currency_id=b["currency_id"],
                        currency_amount=0,
                    )
                )
            if not postings:
                return None
            shown = ".".join(reversed(day.split("-")))
            text = memo or tr("Переоценка валютных остатков на {date}", date=shown)
            return self.post_new(company_id, day, postings, text)

    def _currency_balances(self, company_id: int, day: str) -> list[sqlite3.Row]:
        """Balances of currency accounts on `day` (common layer), in manat and in currency,
        per account, subconto values and currency."""
        return self.conn.execute(
            """
            WITH docs AS (
                SELECT d.id FROM documents d JOIN layers l ON l.id = d.layer_id
                WHERE d.company_id = :company_id AND d.status = 'posted'
                  AND d.doc_date <= :day AND l.code = 'common'
            ),
            moves AS (
                SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc1, p.dt_sc2 AS sc2,
                       p.dt_sc3 AS sc3, p.currency_id, p.amount, p.currency_amount
                FROM postings p JOIN docs ON docs.id = p.document_id
                JOIN accounts a ON a.id = p.debit_account_id
                WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
                UNION ALL
                SELECT p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, p.currency_id,
                       -p.amount, -p.currency_amount
                FROM postings p JOIN docs ON docs.id = p.document_id
                JOIN accounts a ON a.id = p.credit_account_id
                WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
            )
            SELECT m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id, c.code,
                   SUM(m.amount) AS balance, SUM(m.currency_amount) AS currency_balance
            FROM moves m JOIN currencies c ON c.id = m.currency_id
            GROUP BY m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id
            ORDER BY m.account_id, c.code, m.sc1, m.sc2, m.sc3
            """,
            {"company_id": company_id, "day": day},
        ).fetchall()

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
        return insert(
            self.conn,
            "INSERT INTO documents (company_id, number, doc_date, memo, status, layer_id, "
            "reversal_of, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (
                company_id,
                number,
                iso_date(doc_date),
                memo,
                self._layer_id(company_id, layer),
                reversal_of,
                now(),
            ),
        )

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
            try:
                invoice = normalize_invoice(p.invoice)
            except ValidationError as e:
                raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
            currency_amount = None
            if p.currency_id is not None:
                try:
                    currency_amount = to_minor(
                        p.currency_amount if p.currency_amount is not None else 0
                    )
                except (TypeError, ValueError) as e:
                    raise ValidationError(
                        tr("строка {line}: {error}", line=line_no, error=e)
                    ) from e
            rows.append(
                (
                    company_id,
                    doc_id,
                    line_no,
                    p.debit_account_id,
                    p.credit_account_id,
                    amount,
                    *pad_subconto(p.debit_subconto, line_no),
                    *pad_subconto(p.credit_subconto, line_no),
                    p.memo,
                    p.currency_id,
                    currency_amount,
                    invoice,
                    _invoice_kind(p) if invoice else None,
                )
            )
        try:
            self.conn.executemany(
                "INSERT INTO postings (company_id, document_id, line_no, debit_account_id, "
                "credit_account_id, amount, dt_sc1, dt_sc2, dt_sc3, ct_sc1, ct_sc2, ct_sc3, memo, "
                "currency_id, currency_amount, invoice, invoice_kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        except sqlite3.IntegrityError as e:
            raise ValidationError(
                tr("счёт, субконто или валюта не существует или принадлежит другой компании")
            ) from e

    def _post(self, company_id: int, doc_id: int) -> None:
        doc = self._document(company_id, doc_id)
        self._require_draft(doc)
        self._validate_for_posting(company_id, doc)
        self.conn.execute(
            "UPDATE documents SET status = 'posted', posted_at = ? WHERE id = ?", (now(), doc_id)
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

        accounts = self._rows_by_id(
            "accounts",
            company_id,
            {p[f"{side}_account_id"] for p in postings for side, _ in SIDES},
        )
        values = self._rows_by_id(
            "subconto_values",
            company_id,
            {
                p[f"{prefix}_sc{i}"]
                for p in postings
                for _, prefix in SIDES
                for i in range(1, MAX_SUBCONTO + 1)
            }
            - {None},
        )
        owners = {v["owner_id"] for v in values.values()} - {None} - set(values)
        values |= self._rows_by_id("subconto_values", company_id, owners)

        control = self.conn.execute(
            "SELECT account_id FROM account_roles WHERE company_id = ? AND role = ?",
            (company_id, OPENING_BALANCE),
        ).fetchone()
        if (
            control is not None
            and control["account_id"] in accounts
            and not is_opening_document(self.conn, company_id, doc["id"])
        ):
            raise ValidationError(
                tr("счёт ввода начальных остатков проводится только в разделе «Начальные остатки»")
            )

        is_reversal = doc["reversal_of"] is not None
        currencies = {
            r["id"]: r["code"]
            for r in self.conn.execute(
                "SELECT id, code FROM currencies WHERE company_id = ?", (company_id,)
            )
        }
        # a contract may stay empty: many suppliers have none, only the e-qaimə
        optional = {
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM subconto_kinds WHERE company_id = ? AND owner_kind_id IS NOT NULL",
                (company_id,),
            )
        }
        for p in postings:
            line = p["line_no"]
            self._validate_currency(p, accounts, values, currencies)
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
                    code=account_label(acc),
                )
                if acc["is_group"]:
                    raise ValidationError(
                        tr("{label}: нельзя проводить на группу счетов", label=label)
                    )
                if not acc["active"] and not is_reversal:
                    raise ValidationError(tr("{label}: счёт не активен", label=label))
                self._validate_subconto(acc, p, prefix, label, values, optional)
                if not is_reversal:
                    self._validate_owners(p, prefix, label, values)

    def _rows_by_id(self, table: str, company_id: int, ids: set[int]) -> dict[int, sqlite3.Row]:
        """Rows of a company table (accounts, subconto_values) with these ids, by id."""
        if not ids:
            return {}
        rows = self.conn.execute(
            f"SELECT * FROM {table} "
            "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
            (company_id, json.dumps(sorted(ids))),
        )
        return {r["id"]: r for r in rows}

    @staticmethod
    def _validate_subconto(
        acc: sqlite3.Row,
        p: sqlite3.Row,
        prefix: str,
        label: str,
        values: dict[int, sqlite3.Row],
        optional: set[int],
    ) -> None:
        """Each subconto position of the account is filled with a value of its kind; one
        of an `optional` kind (a contract) may be left empty."""
        for i in range(1, MAX_SUBCONTO + 1):
            kind_id = acc[f"sc{i}_kind_id"]
            value_id = p[f"{prefix}_sc{i}"]
            if kind_id is None:
                if value_id is not None:
                    raise ValidationError(tr("{label}: у счёта нет субконто {i}", label=label, i=i))
                continue
            if value_id is None:
                if kind_id in optional:
                    continue
                raise ValidationError(tr("{label}: не заполнено субконто {i}", label=label, i=i))
            if values[value_id]["kind_id"] != kind_id:
                raise ValidationError(tr("{label}: субконто {i} не того вида", label=label, i=i))

    @staticmethod
    def _validate_owners(
        p: sqlite3.Row, prefix: str, label: str, values: dict[int, sqlite3.Row]
    ) -> None:
        """A contract of a counterparty goes only next to that counterparty."""
        side = [values[v] for i in range(1, MAX_SUBCONTO + 1) if (v := p[f"{prefix}_sc{i}"])]
        for value in side:
            if value["owner_id"] is None:
                continue
            owner = values[value["owner_id"]]
            other = next(
                (w for w in side if w["kind_id"] == owner["kind_id"] and w["id"] != owner["id"]),
                None,
            )
            if other is not None:
                raise ValidationError(
                    tr(
                        "{label}: «{name}» относится к «{owner}», а не к «{other}»",
                        label=label,
                        name=value["name"],
                        owner=owner["name"],
                        other=other["name"],
                    )
                )

    @staticmethod
    def _validate_currency(
        p: sqlite3.Row,
        accounts: dict[int, sqlite3.Row],
        values: dict[int, sqlite3.Row],
        currencies: dict[int, str],
    ) -> None:
        """A side on a currency account needs the posting's currency, unless the account
        takes manat too (CURRENCY_OPTIONAL) and no element of that side has a currency;
        a posting without currency accounts has no currency. Elements with a currency
        (a USD bank account, a contract in EUR) accept only that currency."""
        line = p["line_no"]
        currency_sides = [
            (side, prefix)
            for side, prefix in SIDES
            if accounts[p[f"{side}_account_id"]]["currency"]
        ]
        if not currency_sides:
            if p["currency_id"] is not None:
                raise ValidationError(
                    tr("строка {line}: валюта указана, но счета без валютного учёта", line=line)
                )
            return
        for side, prefix in currency_sides:
            label = tr(
                "строка {line}, {side} {code}",
                line=line,
                side=tr("Дт" if side == "debit" else "Кт"),
                code=account_label(accounts[p[f"{side}_account_id"]]),
            )
            optional = accounts[p[f"{side}_account_id"]]["currency"] == CURRENCY_OPTIONAL
            for i in range(1, MAX_SUBCONTO + 1):
                value = values.get(p[f"{prefix}_sc{i}"])
                if value is None or value["currency_id"] is None:
                    continue
                if p["currency_id"] is None:
                    raise ValidationError(
                        tr(
                            "{label}: «{name}» в валюте {expected} — укажите сумму в валюте",
                            label=label,
                            name=value["name"],
                            expected=currencies.get(value["currency_id"], "?"),
                        )
                    )
                if value["currency_id"] != p["currency_id"]:
                    raise ValidationError(
                        tr(
                            "{label}: «{name}» в валюте {expected}, а проводка в {actual}",
                            label=label,
                            name=value["name"],
                            expected=currencies.get(value["currency_id"], "?"),
                            actual=currencies[p["currency_id"]],
                        )
                    )
            if p["currency_id"] is None and not optional:
                raise ValidationError(tr("{label}: не указана валюта", label=label))
        if p["currency_id"] is not None and p["currency_amount"] * p["amount"] < 0:
            raise ValidationError(
                tr(
                    "строка {line}: сумма в валюте и сумма в манатах разных знаков",
                    line=line,
                )
            )

    def _require_draft(self, doc: sqlite3.Row) -> None:
        if doc["status"] != "draft":
            raise ValidationError(tr("документ №{n} уже проведён и не изменяется", n=doc["number"]))

    def _document(self, company_id: int, doc_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT d.*, l.code AS layer FROM documents d JOIN layers l ON l.id = d.layer_id "
            "WHERE d.company_id = ? AND d.id = ?",
            (company_id, doc_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("документ {id} не найден", id=doc_id))
        return row

    def _layer_id(self, company_id: int, code: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM layers WHERE company_id = ? AND code = ?", (company_id, code)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("слой {code} не найден", code=code))
        return row["id"]


def _invoice_kind(p: PostingInput) -> str | None:
    """Stored kind of the posting's number: None for an e-qaimə (or no number)."""
    if p.invoice_kind not in KINDS:
        raise ValidationError(tr("неизвестный вид документа: {kind}", kind=p.invoice_kind))
    return p.invoice_kind or None if normalize_invoice(p.invoice) else None
