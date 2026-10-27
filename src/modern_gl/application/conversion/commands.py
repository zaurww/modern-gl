"""Currency conversion (D37): a document that builds its own GL postings through transit.

Dt 57 / Ct the account debited — at the Central Bank's rate of the debit date;
Dt the account credited / Ct 57 — at the same date's rate (manat: the amount itself);
what is left on 57 is the exchange difference: Dt 91.2 / Ct 57 (loss) or Dt 57 / Ct 91.1
(gain); each bank fee: Dt 91.2 / Ct the money account it is taken from (either side or
another one, in its currency). A credit made on a later day is a second GL document of
that day; until then the money sits on 57. A fee taken from the account credited goes
with the credit, at the rate of its day.
"""

from __future__ import annotations

from datetime import date

from modern_gl.application.common import pad_subconto
from modern_gl.application.conversion.calc import (
    Conversion,
    ConversionCalc,
    ConversionFee,
    ConversionInput,
    ConversionSide,
    calculate,
    fee_on_credit,
    load_conversion,
    same_day,
)
from modern_gl.application.currencies import no_rate_text
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.documents import explain_owner
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.module import ModuleDocumentCommands
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import Row, transaction

EXCHANGE_DIFFERENCE = "Курсовая разница при конвертации"
BANK_FEE_ITEM = "Комиссия банка"


def require_sides(data: ConversionInput) -> tuple[ConversionSide, ConversionSide]:
    """What left one account and what came to the other, in different currencies."""
    source, target = data.source, data.target
    if source is None or not source.amount:
        raise ValidationError(tr("не указано, с какого счёта списано"))
    if target is None or not target.amount:
        raise ValidationError(tr("не указано, на какой счёт зачислено"))
    if source.currency_id == target.currency_id:
        raise ValidationError(tr("валюта списания и зачисления одинаковая — это не конвертация"))
    return source, target


def posting_line(
    debit: int,
    credit: int,
    amount: int,
    debit_sc=(),
    credit_sc=(),
    text: str = "",
    currency_id: int | None = None,
    currency_amount: int = 0,
) -> PostingInput:
    """A posting of the conversion; amounts in kopecks."""
    return PostingInput(
        debit,
        credit,
        from_minor(amount),
        debit_sc,
        credit_sc,
        text,
        currency_id,
        None if currency_id is None else from_minor(currency_amount),
    )


explain_owner(
    "conversion",
    lambda _role, _n, _m: tr("проводки созданы документом «Конвертация валюты»; исправьте его там"),
)


class MissingAccountRole(ValidationError):
    """No account for a role of conversions: the form asks for it on the spot."""

    def __init__(self, role: str, message: str) -> None:
        super().__init__(message)
        self.role = role


class ConversionCommands(ModuleDocumentCommands):
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

    def rebuild_postings(self, company_id: int, since: date | str) -> list[int]:
        """Build the GL documents of posted conversions from `since` on (not in the closed
        period) again from the conversions (D101); the GL documents that changed."""
        return self._rebuild_each(
            company_id,
            since,
            "currency_conversions",
            lambda conversion_id: self._rebuild_conversion(
                company_id, load_conversion(self.conn, company_id, conversion_id)
            ),
            lambda n, day, error: tr(
                "конвертация №{n} от {date}: {error}", n=n, date=day, error=error
            ),
        )

    # ---- internals --------------------------------------------------------------------

    def _check_input(self, company_id: int, data: ConversionInput) -> None:
        iso_date(data.doc_date)
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
        for fee in data.fees:
            if fee.amount <= 0:
                raise ValidationError(tr("комиссия должна быть больше нуля"))
            self._account(company_id, fee.account_id)
            pad_subconto(fee.subconto)
            if fee.currency_id is not None:
                self._currency(company_id, fee.currency_id)
            if fee.expense_account_id is not None:
                self._account(company_id, fee.expense_account_id)

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
            "to_currency_id = ?, to_amount = ?, to_reference = ?, to_date = ? "
            "WHERE company_id = ? AND id = ?",
            (*side(data.source), *side(data.target), target_date, company_id, conversion_id),
        )
        self.conn.execute(
            "DELETE FROM conversion_fees WHERE company_id = ? AND conversion_id = ?",
            (company_id, conversion_id),
        )
        self.conn.executemany(
            "INSERT INTO conversion_fees (company_id, conversion_id, line_no, account_id, "
            "sc1, sc2, sc3, currency_id, amount, expense_account_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    company_id,
                    conversion_id,
                    line_no,
                    fee.account_id,
                    *pad_subconto(fee.subconto),
                    fee.currency_id,
                    fee.amount,
                    fee.expense_account_id,
                )
                for line_no, fee in enumerate(data.fees, start=1)
            ],
        )

    def _post_conversion(self, company_id: int, conversion_id: int, data: ConversionInput) -> None:
        debit_lines, credit_lines = self._conversion_postings(company_id, data)
        row = self._conversion_row(company_id, conversion_id)
        if same_day(data):
            lines = debit_lines + credit_lines
            self._write_module_document(
                company_id, row["document_id"], data.doc_date, lines, data.memo
            )
            self._drop_credit_document(company_id, row)
            return
        self._write_module_document(
            company_id, row["document_id"], data.doc_date, debit_lines, data.memo
        )
        target_date = data.target_date or data.doc_date
        if row["credit_document_id"] is not None:
            self._write_module_document(
                company_id, row["credit_document_id"], target_date, credit_lines, data.memo
            )
            return
        credit_id = self._insert_document(company_id, target_date, data.memo, "common")
        self._insert_postings(company_id, credit_id, credit_lines)
        self._post(company_id, credit_id)
        self.conn.execute(
            "UPDATE currency_conversions SET credit_document_id = ? WHERE id = ?",
            (credit_id, conversion_id),
        )

    def _conversion_postings(
        self, company_id: int, data: ConversionInput
    ) -> tuple[list[PostingInput], list[PostingInput]]:
        """Postings of the debit date and of the credit date (the same day: both lists go
        into one document)."""
        source, target = require_sides(data)
        transit = self._transit_account(company_id)
        calc, source_value, target_value = self._calculated(company_id, data)
        memo = trd(
            "Конвертация {source} → {target}",
            source=self._code(company_id, source.currency_id),
            target=self._code(company_id, target.currency_id),
        )
        debit_lines = [
            posting_line(
                transit["id"],
                source.account_id,
                source_value,
                (),
                source.subconto,
                memo,
                currency_id=source.currency_id,
                currency_amount=source.amount,
            )
        ]
        difference = self._difference_line(company_id, transit["id"], calc.difference or 0)
        if difference is not None:
            debit_lines.append(difference)
        credit_lines = [
            posting_line(
                target.account_id,
                transit["id"],
                target_value,
                target.subconto,
                (),
                memo,
                currency_id=target.currency_id,
                currency_amount=target.amount,
            )
        ]
        for fee, value in zip(data.fees, calc.fee_values, strict=True):
            posting = self._fee_line(company_id, fee, value or 0)
            (credit_lines if fee_on_credit(data, fee) else debit_lines).append(posting)
        return debit_lines, credit_lines

    def _rebuild_conversion(self, company_id: int, conversion: Conversion) -> list[int]:
        """Its one or two GL documents again; a credit made on another day keeps its own."""
        debit_lines, credit_lines = self._conversion_postings(company_id, conversion)
        credit_id = conversion.credit_document_id
        if same_day(conversion):
            parts = [(conversion.document_id, conversion.doc_date, debit_lines + credit_lines)]
        elif credit_id is None:  # posted on two days: the credit has a document of its own
            raise ValidationError(tr("у проведённой конвертации нет документа зачисления"))
        else:
            parts = [
                (conversion.document_id, conversion.doc_date, debit_lines),
                (credit_id, conversion.target_date or conversion.doc_date, credit_lines),
            ]
        return [
            doc_id
            for doc_id, day, lines in parts
            if self._rebuild_module_document(company_id, doc_id, day, lines, conversion.memo)
        ]

    def _transit_account(self, company_id: int) -> Row:
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
        return transit

    def _calculated(
        self, company_id: int, data: ConversionInput
    ) -> tuple[ConversionCalc, int, int]:
        """The calculation and the manat values of both sides; a currency without a rate
        stops it, as does a side left out."""
        calc = calculate(self.conn, company_id, data)
        if calc.missing:
            codes = ", ".join(self._currency(company_id, c)["code"] for c in calc.missing)
            raise ValidationError(no_rate_text(codes, data.doc_date))
        if calc.source_value is None:
            raise ValidationError(tr("не указано, с какого счёта списано"))
        if calc.target_value is None:
            raise ValidationError(tr("не указано, на какой счёт зачислено"))
        return calc, calc.source_value, calc.target_value

    def _difference_line(
        self, company_id: int, transit_id: int, difference: int
    ) -> PostingInput | None:
        """The exchange difference: a loss (Dt loss / Kt transit) or a gain (the other way)."""
        if not difference:
            return None
        text = trd(EXCHANGE_DIFFERENCE)
        if difference > 0:
            loss = self._role_account(
                company_id, FX_LOSS, tr("Не указан счёт убытка от курсовой разницы")
            )
            sc = self.named_subconto(company_id, loss["id"], text)
            return posting_line(loss["id"], transit_id, difference, sc, (), text)
        gain = self._role_account(
            company_id, FX_GAIN, tr("Не указан счёт дохода от курсовой разницы")
        )
        sc = self.named_subconto(company_id, gain["id"], text)
        return posting_line(transit_id, gain["id"], -difference, (), sc, text)

    def _fee_line(self, company_id: int, fee: ConversionFee, value: int) -> PostingInput:
        """A bank fee: Dt its expense account (or the bank fee role) / Kt the money account."""
        text = trd(BANK_FEE_ITEM)
        if fee.expense_account_id is not None:
            expense = self._account(company_id, fee.expense_account_id)
        else:
            expense = self._role_account(company_id, BANK_FEE, tr("Не указан счёт комиссии банка"))
        return posting_line(
            expense["id"],
            fee.account_id,
            value,
            self.named_subconto(company_id, expense["id"], text),
            fee.subconto,
            text,
            currency_id=fee.currency_id,
            currency_amount=fee.amount,
        )

    def _role_account(self, company_id: int, role: str, missing: str) -> Row:
        account_id = self.account_role(company_id, role)
        if account_id is None:
            raise MissingAccountRole(
                role, missing + ". " + tr("Выберите его в «Счета конвертации» (меню «⋯»).")
            )
        return self._account(company_id, account_id)

    def _code(self, company_id: int, currency_id: int | None) -> str:
        if currency_id is None:
            return self._company(company_id)["base_currency"]
        return self._currency(company_id, currency_id)["code"]

    def _conversion_row(self, company_id: int, conversion_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM currency_conversions WHERE company_id = ? AND id = ?",
            (company_id, conversion_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("документ {id} не найден", id=conversion_id))
        return row

    def _require_conversion_changeable(self, company_id: int, row: Row) -> None:
        for doc_id in (row["document_id"], row["credit_document_id"]):
            if doc_id is not None:
                doc = self._document(company_id, doc_id)
                if doc["status"] == "posted":
                    self._require_changeable(company_id, doc)

    def _drop_credit_document(self, company_id: int, row: Row) -> None:
        if row["credit_document_id"] is None:
            return
        self.conn.execute(
            "UPDATE currency_conversions SET credit_document_id = NULL WHERE id = ?", (row["id"],)
        )
        self._remove_document(company_id, self._document(company_id, row["credit_document_id"]))
