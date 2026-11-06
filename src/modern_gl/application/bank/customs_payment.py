"""A payment to the customs: one line of the bank's statement, several things paid (D212).

The fees go to the account of a batch's expenses (15); the terminal's part closes its debt
on 60, its e-qaimə accrues it; the ƏDV of the declaration is accrued here, as nothing else
accrues it, and paid at once on the customs' settlement under the declaration's number —
that is what the credit of the ƏDV reads (`vat/facts.py`)."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.bank.deposit_commands import VatDepositCommands
from modern_gl.application.bank.operations import OTHER, OUT, BankLine, BankOperationInput
from modern_gl.application.common import Subconto, fill_subconto
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT, INPUT_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import from_minor
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
    def save_customs_payment(self, company_id: int, payment: CustomsPayment) -> int:
        """The bank's operation and the accrual of the ƏDV: both or neither."""
        lines = self._customs_lines(company_id, payment)
        if not lines:
            raise ValidationError(tr("укажите сумму платежа"))
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
