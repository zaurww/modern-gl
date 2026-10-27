"""Opening balances: one ordinary, balanced GL document per company (D39)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta

from modern_gl.application.ledger.chart import ChartCommands
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.queries import opening_document
from modern_gl.domain.accounts import OPENING_BALANCE
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

OPENING_CODE = "00"


def opening_posting(line: PostingInput, on_credit: bool) -> PostingInput:
    """A balance typed as «Дт account / Кт 00»: a credit balance is the other way round,
    «Дт 00 / Кт account» (debt 9: the rule was in the window)."""
    if not on_credit:
        return line
    return replace(
        line,
        debit_account_id=line.credit_account_id,
        debit_subconto=line.credit_subconto,
        credit_account_id=line.debit_account_id,
        credit_subconto=line.debit_subconto,
    )


class OpeningBalanceCommands(ChartCommands, DocumentCommands):
    """Use cases of opening balances: one balanced document against account "00" (D39)."""

    def opening_account(self, company_id: int, create: bool = True) -> int:
        """The counter-account of opening balances ("00", as in 1C), created on first use;
        `create=False` (a company open for viewing, D80) only finds it, or NotFoundError.

        It is shown in the chart and in reports, but only the opening balances post to it:
        while it is not zero, the balances entered so far do not agree.
        """
        existing = self.account_role(company_id, OPENING_BALANCE)
        if not create:
            if existing is None:
                raise NotFoundError(tr("Начальные остатки не вводились"))
            return existing
        taken = self.conn.execute(
            "SELECT 1 FROM accounts WHERE company_id = ? AND code = ?",
            (company_id, OPENING_CODE),
        ).fetchone()
        if existing is not None:
            if self._account(company_id, existing)["code"] is None and not taken:
                # made hidden and without a code before the difference was allowed
                self.update_account(
                    company_id, existing, new_code=OPENING_CODE, name=tr("Ввод начальных остатков")
                )
            return existing
        with transaction(self.conn):
            account_id = self.add_account(
                company_id,
                None if taken else OPENING_CODE,
                tr("Ввод начальных остатков"),
                account_class="equity",
                account_type="other_equity",
                two_sided=True,
            )
            self.set_account_role(company_id, OPENING_BALANCE, account_id)
        return account_id

    def save_opening_balances(
        self,
        company_id: int,
        effective_date: date | str,
        postings: Sequence[PostingInput],
        *,
        post: bool,
        memo: str,
    ) -> int:
        """Create or replace the company's opening balances.

        Every input line has the counter-account on exactly one side.  Debit balances
        credit it; credit balances debit it.  Totals that differ are allowed — the balances
        may come in parts — and the difference stays visible on that account.  The
        document is dated the day before `effective_date`, so a report that starts on that
        day shows the balances as its opening.
        """
        control = self.opening_account(company_id)
        if not postings:
            raise ValidationError(tr("не введены начальные остатки"))
        for line, item in enumerate(postings, start=1):
            if (item.debit_account_id == control) == (item.credit_account_id == control):
                raise ValidationError(
                    tr("строка {line}: неверная строка начальных остатков", line=line)
                )
            if to_minor(item.amount) <= 0:
                raise ValidationError(tr("строка {line}: сумма должна быть больше нуля", line=line))

        effective = date.fromisoformat(iso_date(effective_date))
        document_date = effective - timedelta(days=1)
        with transaction(self.conn):
            current = opening_document(self.conn, company_id)
            if current is None:
                doc_id = self.create_draft(company_id, document_date, postings, memo)
                self.conn.execute(
                    "INSERT INTO opening_balance_documents "
                    "(company_id, document_id, effective_date) VALUES (?, ?, ?)",
                    (company_id, doc_id, effective.isoformat()),
                )
                if post:
                    self.post(company_id, doc_id)
                return doc_id

            doc_id = current.document_id
            self.conn.execute(
                "UPDATE opening_balance_documents SET effective_date = ? WHERE company_id = ?",
                (effective.isoformat(), company_id),
            )
            if current.status == "posted":
                self.repost(company_id, doc_id, document_date, postings, memo)
            else:
                self.update_draft(company_id, doc_id, document_date, postings, memo)
                if post:
                    self.post(company_id, doc_id)
            return doc_id
