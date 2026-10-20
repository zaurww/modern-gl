"""Currency conversion (D37): a document that builds its own GL postings through transit.

Dt 57 / Ct the account debited — at the Central Bank's rate of the debit date;
Dt the account credited / Ct 57 — at the same date's rate (manat: the amount itself);
what is left on 57 is the exchange difference: Dt 91.2 / Ct 57 (loss) or Dt 57 / Ct 91.1
(gain); the bank fee: Dt 91.2 / Ct the bank account it is taken from. A credit made on a
later day is a second GL document of that day; until then the money sits on 57.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from modern_gl.application.common import pad_subconto
from modern_gl.application.conversions import (
    FEE_SIDES,
    ConversionInput,
    ConversionSide,
    calculate,
    same_day,
)
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.chart import ChartCommands
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

EXCHANGE_DIFFERENCE = "Курсовая разница при конвертации"
BANK_FEE_ITEM = "Комиссия банка"


class MissingAccountRole(ValidationError):
    """No account for a role of conversions: the form asks for it on the spot."""

    def __init__(self, role: str, message: str) -> None:
        super().__init__(message)
        self.role = role


class ConversionCommands(ChartCommands, DocumentCommands):
    def save_conversion(
        self,
        company_id: int,
        data: ConversionInput,
        conversion_id: int | None = None,
        *,
        post: bool,
    ) -> int:
        """Create or change a conversion; `post` builds and posts its GL documents.

        A posted conversion is changed in place (D32): its documents keep their numbers.
        A draft keeps only what was entered — its GL document has no postings yet.
        """
        self._check_input(company_id, data)
        with transaction(self.conn):
            if conversion_id is None:
                doc_id = self._insert_document(company_id, data.doc_date, data.memo, "common")
                saved: int = self.conn.execute(
                    "INSERT INTO currency_conversions (company_id, document_id) VALUES (?, ?) "
                    "RETURNING id",
                    (company_id, doc_id),
                ).fetchone()[0]
                action = "create"
            else:
                saved = conversion_id
                row = self._conversion_row(company_id, saved)
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
                    self._require_conversion_changeable(company_id, row)
                action = "update"
            self._store(company_id, saved, data)
            if post:
                self._post_conversion(company_id, saved, data)
                action = "post"
            else:
                row = self._conversion_row(company_id, saved)
                self.conn.execute(
                    "UPDATE documents SET doc_date = ?, memo = ? WHERE id = ?",
                    (iso_date(data.doc_date), data.memo, row["document_id"]),
                )
            self._audit(company_id, "conversion", saved, action, {})
        return saved

    def unpost_conversion(self, company_id: int, conversion_id: int) -> None:
        """Back to a draft: its postings go (the audit trail keeps them)."""
        with transaction(self.conn):
            row = self._conversion_row(company_id, conversion_id)
            doc = self._document(company_id, row["document_id"])
            if doc["status"] != "posted":
                raise ValidationError(tr("документ №{n} не проведён", n=doc["number"]))
            self._require_conversion_changeable(company_id, row)
            snapshot = self._snapshot(doc)
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?", (doc["id"],)
            )
            self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc["id"],))
            self._drop_credit_document(company_id, row)
            self._audit(company_id, "document", doc["id"], "unpost", snapshot)
            self._audit(company_id, "conversion", conversion_id, "unpost", {})

    def delete_conversion(self, company_id: int, conversion_id: int) -> None:
        with transaction(self.conn):
            row = self._conversion_row(company_id, conversion_id)
            doc = self._document(company_id, row["document_id"])
            if doc["status"] == "posted":
                self._require_conversion_changeable(company_id, row)
            self._drop_credit_document(company_id, row)
            self.conn.execute("DELETE FROM currency_conversions WHERE id = ?", (conversion_id,))
            self._remove_document(company_id, doc)
            self._audit(company_id, "conversion", conversion_id, "delete", {})

    # ---- internals --------------------------------------------------------------------

    def _check_input(self, company_id: int, data: ConversionInput) -> None:
        iso_date(data.doc_date)
        if data.fee_side not in FEE_SIDES:
            raise ValidationError(tr("неизвестная сторона комиссии: {side}", side=data.fee_side))
        if data.fee_amount < 0:
            raise ValidationError(tr("комиссия не может быть отрицательной"))
        if data.target_date is not None and iso_date(data.target_date) < iso_date(data.doc_date):
            raise ValidationError(tr("дата зачисления раньше даты списания"))
        for side in (data.source, data.target):
            if side is None:
                continue
            if side.amount < 0:
                raise ValidationError(tr("сумма должна быть больше нуля"))
            self._account(company_id, side.account_id)
            pad_subconto(side.subconto)
            if side.currency_id is not None:
                self._currency(company_id, side.currency_id)
        if data.fee_account_id is not None:
            self._account(company_id, data.fee_account_id)

    def _store(self, company_id: int, conversion_id: int, data: ConversionInput) -> None:
        def side(s: ConversionSide | None) -> tuple:
            if s is None:
                return (None, None, None, None, None, None, "")
            return (
                s.account_id,
                *pad_subconto(s.subconto),
                s.currency_id,
                s.amount or None,
                s.reference.strip(),
            )

        target_date = None if same_day(data) else iso_date(data.target_date or data.doc_date)
        self.conn.execute(
            "UPDATE currency_conversions SET "
            "from_account_id = ?, from_sc1 = ?, from_sc2 = ?, from_sc3 = ?, "
            "from_currency_id = ?, from_amount = ?, from_reference = ?, "
            "to_account_id = ?, to_sc1 = ?, to_sc2 = ?, to_sc3 = ?, "
            "to_currency_id = ?, to_amount = ?, to_reference = ?, to_date = ?, "
            "fee_amount = ?, fee_side = ?, fee_account_id = ? "
            "WHERE company_id = ? AND id = ?",
            (
                *side(data.source),
                *side(data.target),
                target_date,
                data.fee_amount,
                data.fee_side,
                data.fee_account_id,
                company_id,
                conversion_id,
            ),
        )

    def _post_conversion(self, company_id: int, conversion_id: int, data: ConversionInput) -> None:
        debit_lines, credit_lines = self._conversion_postings(company_id, data)
        row = self._conversion_row(company_id, conversion_id)
        if same_day(data):
            lines = debit_lines + credit_lines
            self._write(company_id, row["document_id"], data.doc_date, lines, data)
            self._drop_credit_document(company_id, row)
            return
        self._write(company_id, row["document_id"], data.doc_date, debit_lines, data)
        target_date = data.target_date or data.doc_date
        if row["credit_document_id"] is not None:
            self._write(company_id, row["credit_document_id"], target_date, credit_lines, data)
            return
        credit_id = self._insert_document(company_id, target_date, data.memo, "common")
        self._insert_postings(company_id, credit_id, credit_lines)
        self._post(company_id, credit_id)
        self.conn.execute(
            "UPDATE currency_conversions SET credit_document_id = ? WHERE id = ?",
            (credit_id, conversion_id),
        )

    def _write(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: list[PostingInput],
        data: ConversionInput,
    ) -> None:
        doc = self._document(company_id, doc_id)
        if doc["status"] == "posted":
            if self._same_content(doc, doc_date, postings, data.memo):
                return
            snapshot = self._snapshot(doc)
            self._rewrite(company_id, doc_id, doc_date, postings, data.memo, "common")
            self._audit(company_id, "document", doc_id, "repost", snapshot)
            return
        self.conn.execute(
            "UPDATE documents SET doc_date = ?, memo = ? WHERE id = ?",
            (iso_date(doc_date), data.memo, doc_id),
        )
        self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc_id,))
        self._insert_postings(company_id, doc_id, postings)
        self._post(company_id, doc_id)

    def _conversion_postings(
        self, company_id: int, data: ConversionInput
    ) -> tuple[list[PostingInput], list[PostingInput]]:
        """Postings of the debit date and of the credit date (the same day: both lists go
        into one document)."""
        source, target = data.source, data.target
        if source is None or not source.amount:
            raise ValidationError(tr("не указано, с какого счёта списано"))
        if target is None or not target.amount:
            raise ValidationError(tr("не указано, на какой счёт зачислено"))
        if source.currency_id == target.currency_id:
            raise ValidationError(
                tr("валюта списания и зачисления одинаковая — это не конвертация")
            )
        transit = self._role_account(
            company_id, FX_TRANSIT, tr("Не указан счёт переводов в пути (57)")
        )
        if transit["currency"]:
            raise ValidationError(
                tr(
                    "счёт {code}: переводы в пути ведутся в манатах, без валютного учёта",
                    code=account_label(transit),
                )
            )
        calc = calculate(self.conn, company_id, data)
        if calc.missing:
            codes = ", ".join(self._currency(company_id, c)["code"] for c in calc.missing)
            raise ValidationError(
                tr("нет курса {code} на {date}", code=codes, date=iso_date(data.doc_date))
            )
        assert calc.source_value is not None and calc.target_value is not None
        memo = tr(
            "Конвертация {source} → {target}",
            source=self._code(company_id, source.currency_id),
            target=self._code(company_id, target.currency_id),
        )

        def line(
            debit: int,
            credit: int,
            amount: int,
            debit_sc=(),
            credit_sc=(),
            text: str = memo,
            side: ConversionSide | None = None,
            currency_amount: int | None = None,
        ) -> PostingInput:
            in_currency = side is not None and side.currency_id is not None
            return PostingInput(
                debit,
                credit,
                Decimal(amount).scaleb(-2),
                debit_sc,
                credit_sc,
                text,
                side.currency_id if in_currency and side else None,
                Decimal(currency_amount).scaleb(-2)
                if in_currency and currency_amount is not None
                else None,
            )

        debit_lines = [
            line(
                transit["id"],
                source.account_id,
                calc.source_value,
                (),
                source.subconto,
                side=source,
                currency_amount=source.amount,
            )
        ]
        difference = calc.difference or 0
        if difference:
            text = tr(EXCHANGE_DIFFERENCE)
            if difference > 0:
                loss = self._role_account(
                    company_id, FX_LOSS, tr("Не указан счёт убытка от курсовой разницы")
                )
                sc = self._item_subconto(company_id, loss, text)
                debit_lines.append(line(loss["id"], transit["id"], difference, sc, (), text))
            else:
                gain = self._role_account(
                    company_id, FX_GAIN, tr("Не указан счёт дохода от курсовой разницы")
                )
                sc = self._item_subconto(company_id, gain, text)
                debit_lines.append(line(transit["id"], gain["id"], -difference, (), sc, text))
        credit_lines = [
            line(
                target.account_id,
                transit["id"],
                calc.target_value,
                target.subconto,
                (),
                side=target,
                currency_amount=target.amount,
            )
        ]
        if data.fee_amount:
            if data.fee_account_id is not None:
                fee_account = self._account(company_id, data.fee_account_id)
            else:
                fee_account = self._role_account(
                    company_id, BANK_FEE, tr("Не указан счёт комиссии банка")
                )
            text = tr(BANK_FEE_ITEM)
            sc = self._item_subconto(company_id, fee_account, text)
            payer = source if data.fee_side == "from" else target
            fee = line(
                fee_account["id"],
                payer.account_id,
                calc.fee_value,
                sc,
                payer.subconto,
                text,
                side=payer,
                currency_amount=data.fee_amount,
            )
            (debit_lines if data.fee_side == "from" else credit_lines).append(fee)
        return debit_lines, credit_lines

    def _role_account(self, company_id: int, role: str, missing: str) -> sqlite3.Row:
        account_id = self.account_role(company_id, role)
        if account_id is None:
            raise MissingAccountRole(
                role, missing + ". " + tr("Выберите его в «Счета конвертации» (меню «⋯»).")
            )
        return self._account(company_id, account_id)

    def _item_subconto(
        self, company_id: int, account: sqlite3.Row, name: str
    ) -> tuple[int | None, ...]:
        """The account's subconto filled with an element of this name (an item of other
        income and expenses, a cost item…), made on first use."""
        values: list[int | None] = []
        for i in (1, 2, 3):
            kind_id = account[f"sc{i}_kind_id"]
            if kind_id is None:
                values.append(None)
                continue
            found = self.conn.execute(
                "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? "
                "AND name = ? ORDER BY active DESC, id LIMIT 1",
                (company_id, kind_id, name),
            ).fetchone()
            values.append(found[0] if found else self.add_subconto_value(company_id, kind_id, name))
        return tuple(values)

    def _code(self, company_id: int, currency_id: int | None) -> str:
        if currency_id is None:
            return self._company(company_id)["base_currency"]
        return self._currency(company_id, currency_id)["code"]

    def _conversion_row(self, company_id: int, conversion_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM currency_conversions WHERE company_id = ? AND id = ?",
            (company_id, conversion_id),
        ).fetchone()
        if row is None:
            raise ValidationError(tr("документ {id} не найден", id=conversion_id))
        return row

    def _require_conversion_changeable(self, company_id: int, row: sqlite3.Row) -> None:
        for doc_id in (row["document_id"], row["credit_document_id"]):
            if doc_id is not None:
                doc = self._document(company_id, doc_id)
                if doc["status"] == "posted":
                    self._require_changeable(company_id, doc)

    def _drop_credit_document(self, company_id: int, row: sqlite3.Row) -> None:
        if row["credit_document_id"] is None:
            return
        self.conn.execute(
            "UPDATE currency_conversions SET credit_document_id = NULL WHERE id = ?", (row["id"],)
        )
        self._remove_document(company_id, self._document(company_id, row["credit_document_id"]))

    def _remove_document(self, company_id: int, doc: sqlite3.Row) -> None:
        snapshot = self._snapshot(doc)
        if doc["status"] == "posted":  # immutability triggers allow only this path
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?",
                (doc["id"],),
            )
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
        self._audit(company_id, "document", doc["id"], "delete", snapshot)
