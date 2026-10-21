"""Documents: drafts, posting and corrections."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date

from modern_gl.application.common import insert, now, pad_subconto
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.validation import PostingChecks
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.domain.invoice import KINDS, normalize_invoice
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class DocumentCommands(PostingChecks):
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
            "SELECT number FROM inventory_documents "
            "WHERE gl_document_id = ? OR accrual_document_id = ?",
            (doc_id, doc_id),
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
        if code != "common":  # a document in an adjustment layer shows the books (D63)
            self.conn.execute("UPDATE companies SET parallel_books = 1 WHERE id = ?", (company_id,))
        return row["id"]


def _invoice_kind(p: PostingInput) -> str | None:
    """Stored kind of the posting's number: None for an e-qaimə (or no number)."""
    if p.invoice_kind not in KINDS:
        raise ValidationError(tr("неизвестный вид документа: {kind}", kind=p.invoice_kind))
    return p.invoice_kind or None if normalize_invoice(p.invoice) else None
