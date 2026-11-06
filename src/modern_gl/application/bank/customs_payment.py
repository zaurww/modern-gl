"""A payment to the customs: one line of the bank's statement, several things paid (D212).

The fees go to the account of a batch's expenses (15); the terminal's part closes its debt
on 60, its e-qaimə accrues it; the ƏDV of the declaration is accrued here, as nothing else
accrues it, and paid at once on the customs' settlement under the declaration's number —
that is what the credit of the ƏDV reads (`vat/facts.py`)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from modern_gl.application.bank.deposit_commands import VatDepositCommands
from modern_gl.application.bank.operations import (
    OTHER,
    OUT,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.common import Subconto, fill_subconto
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT, INPUT_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import format_minor, from_minor
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import transaction


@dataclass(frozen=True)
class CustomsPayment:
    """Amounts in kopecks; what was not paid is 0. Without a declaration (a short one that
    has no purchase yet) only the fees and the terminal can be paid."""

    doc_date: str
    account_id: int  # the bank account's GL account
    subconto: tuple[int | None, ...]  # of the bank account
    settlement_account_id: int  # 60
    declaration: str = ""
    fees: int = 0
    terminal: int = 0  # with its ƏDV, as its e-qaimə accrues it
    terminal_party: int | None = None
    vat: int = 0
    customs_party: int | None = None


class CustomsPaymentCommands(VatDepositCommands):
    def save_customs_payment(
        self, company_id: int, payment: CustomsPayment, operation_id: int | None = None
    ) -> int:
        """The bank's operation and the accrual of the ƏDV: both or neither. `operation_id`
        — a line of a loaded statement: it stays the same line, with its day, sum and
        reference; only what it pays is told. The bank's fee is a line of its own there."""
        lines = self._customs_lines(company_id, payment)
        if not lines:
            raise ValidationError(tr("укажите сумму платежа"))
        if operation_id is not None:
            return self._split_loaded_line(company_id, payment, lines, operation_id)
        memo = trd("Таможенный платёж {n}", n=payment.declaration).strip()
        with transaction(self.conn):
            if payment.vat:
                self._accrue_customs_vat(company_id, payment, memo)
            return self.save_bank_operation(
                company_id,
                BankOperationInput(
                    payment.doc_date,
                    OUT,
                    payment.account_id,
                    tuple(lines),
                    OTHER,
                    payment.subconto,
                    memo=memo,
                ),
                post=True,
                checked=True,
            )

    def _split_loaded_line(
        self,
        company_id: int,
        payment: CustomsPayment,
        lines: list[BankLine],
        operation_id: int,
    ) -> int:
        loaded = load_bank_operation(self.conn, company_id, operation_id)
        total = sum(line.amount for line in lines)
        if loaded.direction != OUT or loaded.currency_id is not None:
            raise ValidationError(tr("таможенный платёж — расход в манатах"))
        if total != loaded.total:
            raise ValidationError(
                tr(
                    "по выписке {amount}, в строках {total}: разница {left}",
                    amount=format_minor(loaded.total),
                    total=format_minor(total),
                    left=format_minor(loaded.total - total),
                )
            )
        memo = trd("Таможенный платёж {n}", n=payment.declaration).strip()
        with transaction(self.conn):
            if payment.vat:
                self._accrue_customs_vat(
                    company_id, replace(payment, doc_date=loaded.doc_date), memo
                )
            return self.save_bank_operation(
                company_id,
                BankOperationInput(
                    loaded.doc_date,
                    OUT,
                    loaded.account_id,
                    tuple(lines),
                    OTHER,
                    loaded.subconto,
                    memo=loaded.memo or memo,
                    reference=loaded.reference,
                ),
                operation_id,
                post=True,
                checked=True,
            )

    def _customs_lines(self, company_id: int, payment: CustomsPayment) -> list[BankLine]:
        lines = []
        if payment.fees:
            account = self.ledger.account_role(company_id, BATCH_EXPENSES_ACCOUNT)
            if account is None:
                raise ValidationError(
                    tr("укажите счёт дополнительных расходов в настройках склада")
                )
            lines.append(BankLine(account, payment.fees))
        if payment.terminal:
            sc = self._party_side(company_id, payment.terminal_party, payment)
            lines.append(BankLine(payment.settlement_account_id, payment.terminal, sc))
        if payment.vat:
            if not payment.declaration:
                raise ValidationError(tr("укажите номер декларации: ƏDV идёт в зачёт по нему"))
            sc = self._party_side(company_id, payment.customs_party, payment)
            lines.append(
                BankLine(payment.settlement_account_id, payment.vat, sc, payment.declaration)
            )
        return lines

    def _party_side(self, company_id: int, party: int | None, payment: CustomsPayment) -> Subconto:
        if party is None:
            raise ValidationError(tr("укажите контрагента"))
        kind = self._subconto_value(company_id, party)["kind_id"]
        return fill_subconto(
            self._account(company_id, payment.settlement_account_id), {kind: party}
        )

    def _accrue_customs_vat(self, company_id: int, payment: CustomsPayment, memo: str) -> None:
        """Dt 19 [customs] / Kt 60 [customs] under the declaration: owed, then paid by the
        operation's line on the same settlement."""
        input_vat = self.ledger.account_role(company_id, INPUT_VAT)
        if input_vat is None:
            raise ValidationError(tr("укажите счёт НДС к возмещению в настройках склада"))
        party = payment.customs_party
        if party is None:
            raise ValidationError(tr("укажите контрагента"))
        kind = self._subconto_value(company_id, party)["kind_id"]
        self.ledger.post_new(
            company_id,
            payment.doc_date,
            [
                PostingInput(
                    input_vat,
                    payment.settlement_account_id,
                    from_minor(payment.vat),
                    fill_subconto(self._account(company_id, input_vat), {kind: party}),
                    self._party_side(company_id, party, payment),
                    memo,
                    invoice=payment.declaration,
                    invoice_kind=CUSTOMS,
                )
            ],
            memo,
        )
