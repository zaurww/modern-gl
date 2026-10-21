"""Bank operations (D47): money in or out of one bank account, a document that builds its
own GL postings.

Məxaric (out): Dt the line's account [its subconto] / Ct the bank account — per line;
mədaxil (in): Dt the bank account / Ct the line's account. The purpose of payment is the
memo, the line's e-qaimə goes into its posting (it closes the e-qaimə in the report,
D38). An operation in a currency: each line at the Central Bank's rate of the day, the
amount in the currency kept on the posting.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from modern_gl.application.bank import (
    IN,
    KIND_NAMES,
    OUT,
    VAT_DEPOSIT_KINDS,
    BankLine,
    BankOperationInput,
)
from modern_gl.application.common import pad_subconto
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.module import ModuleDocumentCommands
from modern_gl.domain.currency import to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class BankCommands(ModuleDocumentCommands):
    def save_bank_payment(
        self,
        company_id: int,
        data: BankOperationInput,
        deposit: BankOperationInput | None,
        *,
        post: bool,
    ) -> list[int]:
        """A new payment and its ƏDV part on the ƏDV deposit account (D69): two
        operations, each on its own account, saved both or neither."""
        with transaction(self.conn):
            saved = [self.save_bank_operation(company_id, data, post=post)]
            if deposit is not None:
                saved.append(self.save_bank_operation(company_id, deposit, post=post))
        return saved

    def save_bank_operation(
        self,
        company_id: int,
        data: BankOperationInput,
        operation_id: int | None = None,
        *,
        post: bool,
    ) -> int:
        """Create or change a bank operation; `post` builds and posts its GL document.

        A posted operation is changed in place (D32): its document keeps the number.
        A draft keeps only what was entered — its GL document has no postings yet.
        """
        self._check_bank_input(company_id, data)
        with transaction(self.conn):
            if operation_id is None:
                doc_id = self._insert_document(company_id, data.doc_date, data.memo, "common")
                saved: int = self.conn.execute(
                    "INSERT INTO bank_operations (company_id, document_id, direction) "
                    "VALUES (?, ?, ?) RETURNING id",
                    (company_id, doc_id, data.direction),
                ).fetchone()[0]
                action = "create"
            else:
                saved = operation_id
                row = self._bank_row(company_id, saved)
                doc = self._document(company_id, row["document_id"])
                if doc["status"] == "posted":
                    if not post:
                        raise ValidationError(
                            tr(
                                "документ №{n} проведён: чтобы сохранить его черновиком, "
                                "сначала отмените проведение",
                                n=doc["number"],
                            )
                        )
                    self._require_changeable(company_id, doc)
                doc_id = row["document_id"]
                action = "update"
            self._store_bank(company_id, saved, data)
            if post:
                postings = self._bank_postings(company_id, data)
                self._write_module_document(company_id, doc_id, data.doc_date, postings, data.memo)
                action = "post"
            else:
                self.conn.execute(
                    "UPDATE documents SET doc_date = ?, memo = ? WHERE id = ?",
                    (iso_date(data.doc_date), data.memo, doc_id),
                )
            self._audit(company_id, "bank_operation", saved, action, {})
        return saved

    def unpost_bank_operation(self, company_id: int, operation_id: int) -> None:
        """Back to a draft: its postings go (the audit trail keeps them)."""
        with transaction(self.conn):
            row = self._bank_row(company_id, operation_id)
            doc = self._document(company_id, row["document_id"])
            if doc["status"] != "posted":
                raise ValidationError(tr("документ №{n} не проведён", n=doc["number"]))
            self._require_changeable(company_id, doc)
            snapshot = self._snapshot(doc)
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?", (doc["id"],)
            )
            self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc["id"],))
            self._audit(company_id, "document", doc["id"], "unpost", snapshot)
            self._audit(company_id, "bank_operation", operation_id, "unpost", {})

    def delete_bank_operation(self, company_id: int, operation_id: int) -> None:
        with transaction(self.conn):
            row = self._bank_row(company_id, operation_id)
            doc = self._document(company_id, row["document_id"])
            if doc["status"] == "posted":
                self._require_changeable(company_id, doc)
            self.conn.execute("DELETE FROM bank_operations WHERE id = ?", (operation_id,))
            self._remove_document(company_id, doc)
            self._audit(company_id, "bank_operation", operation_id, "delete", {})

    # ---- internals --------------------------------------------------------------------

    def _check_bank_input(self, company_id: int, data: BankOperationInput) -> None:
        """What a draft must already be: real accounts, elements and a known kind."""
        iso_date(data.doc_date)
        if data.direction not in (IN, OUT):
            raise ValidationError(tr("неизвестное направление операции: {d}", d=data.direction))
        if data.kind not in KIND_NAMES:
            raise ValidationError(tr("неизвестный вид операции: {kind}", kind=data.kind))
        if data.account_id is not None:
            self._account(company_id, data.account_id)
        pad_subconto(data.subconto)
        if data.currency_id is not None:
            self._currency(company_id, data.currency_id)
        if data.counterparty_id is not None:
            self._subconto_value(company_id, data.counterparty_id)
        for line_no, line in enumerate(data.lines, start=1):
            if line.amount < 0:
                raise ValidationError(
                    tr("строка {line}: сумма должна быть больше нуля", line=line_no)
                )
            if line.account_id is not None:
                self._account(company_id, line.account_id)
            pad_subconto(line.subconto, line_no)
            try:
                normalize_invoice(line.invoice)
            except ValidationError as e:
                raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e

    def _store_bank(self, company_id: int, operation_id: int, data: BankOperationInput) -> None:
        self.conn.execute(
            "UPDATE bank_operations SET direction = ?, kind = ?, account_id = ?, "
            "sc1 = ?, sc2 = ?, sc3 = ?, currency_id = ?, counterparty_id = ?, reference = ? "
            "WHERE company_id = ? AND id = ?",
            (
                data.direction,
                data.kind,
                data.account_id,
                *pad_subconto(data.subconto),
                data.currency_id,
                data.counterparty_id,
                data.reference.strip(),
                company_id,
                operation_id,
            ),
        )
        self.conn.execute(
            "DELETE FROM bank_operation_lines WHERE company_id = ? AND operation_id = ?",
            (company_id, operation_id),
        )
        self.conn.executemany(
            "INSERT INTO bank_operation_lines (company_id, operation_id, line_no, account_id, "
            "sc1, sc2, sc3, amount, invoice) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    company_id,
                    operation_id,
                    line_no,
                    line.account_id,
                    *self._line_subconto(company_id, line, data.counterparty_id),
                    line.amount,
                    normalize_invoice(line.invoice) or "",
                )
                for line_no, line in enumerate(data.lines, start=1)
            ],
        )

    def _line_subconto(
        self, company_id: int, line: BankLine, counterparty_id: int | None
    ) -> tuple[int | None, int | None, int | None]:
        """The line's subconto with the operation's counterparty in the account's
        counterparty position, when the line leaves it empty."""
        values = list(pad_subconto(line.subconto))
        if counterparty_id is None or line.account_id is None:
            return values[0], values[1], values[2]
        kind_id = self._subconto_value(company_id, counterparty_id)["kind_id"]
        account = self._account(company_id, line.account_id)
        for i in range(3):
            if account[f"sc{i + 1}_kind_id"] == kind_id and values[i] is None:
                values[i] = counterparty_id
        return values[0], values[1], values[2]

    def _bank_postings(self, company_id: int, data: BankOperationInput) -> list[PostingInput]:
        if data.account_id is None:
            raise ValidationError(tr("не указан банковский счёт"))
        bank = self._account(company_id, data.account_id)
        if bank["account_type"] == "vat_deposit" and data.kind not in VAT_DEPOSIT_KINDS:
            raise ValidationError(
                tr(
                    "с депозитного счёта ƏDV платится только ƏDV: поставщику, от покупателя, "
                    "в бюджет или перевод между своими счетами"
                )
            )
        lines = [line for line in data.lines if line.account_id is not None or line.amount]
        if not lines:
            raise ValidationError(tr("в операции нет строк"))
        rate = None
        if data.currency_id is not None:
            found = rate_on(self.conn, company_id, data.currency_id, data.doc_date)
            if found is None:
                raise ValidationError(
                    tr(
                        "нет курса {code} на {date}",
                        code=self._currency(company_id, data.currency_id)["code"],
                        date=iso_date(data.doc_date),
                    )
                )
            rate = found.per_unit
        bank_sc = pad_subconto(data.subconto)
        postings = []
        for line_no, line in enumerate(lines, start=1):
            if line.account_id is None:
                raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
            if not line.amount:
                raise ValidationError(tr("строка {line}: нулевая сумма", line=line_no))
            sc = self._line_subconto(company_id, line, data.counterparty_id)
            if line.account_id == data.account_id and sc == bank_sc:
                raise ValidationError(
                    tr("строка {line}: деньги переводятся на тот же счёт", line=line_no)
                )
            value = line.amount if rate is None else to_base(line.amount, rate)
            dt, ct = (
                (line.account_id, data.account_id)
                if data.direction == OUT
                else (
                    data.account_id,
                    line.account_id,
                )
            )
            dt_sc, ct_sc = (sc, bank_sc) if data.direction == OUT else (bank_sc, sc)
            postings.append(
                PostingInput(
                    dt,
                    ct,
                    Decimal(value).scaleb(-2),
                    dt_sc,
                    ct_sc,
                    data.memo,
                    data.currency_id,
                    None if data.currency_id is None else Decimal(line.amount).scaleb(-2),
                    line.invoice,
                )
            )
        return postings

    def _bank_row(self, company_id: int, operation_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM bank_operations WHERE company_id = ? AND id = ?",
            (company_id, operation_id),
        ).fetchone()
        if row is None:
            raise ValidationError(tr("документ {id} не найден", id=operation_id))
        return row
