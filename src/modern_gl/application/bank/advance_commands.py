"""«Зачесть авансы» (D78): an advance paid to a supplier (60.2) or by a customer (62.2)
set against the e-qaimə that came after it, oldest first — the payment itself and its
statement stay as they were."""

from __future__ import annotations

from modern_gl.application.bank.advances import AdvanceOffset, counterparty_balance
from modern_gl.application.bank.commands import BankCommands
from modern_gl.application.bank.operations import allocate
from modern_gl.application.common import fill_subconto
from modern_gl.application.invoices import open_invoices
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import Row, transaction

# (the settlement account's type, the advance's role, the company owes the e-qaimə)
OFFSET_SIDES = (("payable", ADVANCE_PAID, True), ("receivable", ADVANCE_RECEIVED, False))


class BankAdvanceCommands(BankCommands):
    def plan_advance_offsets(
        self, company_id: int, day: str, counterparty_id: int
    ) -> list[AdvanceOffset]:
        """«Зачесть авансы» (D78), nothing written: each advance of the counterparty —
        paid to it (60.2) or by it (62.2) — against its unpaid e-qaimə, oldest first."""
        offsets = []
        for settlement_type, role, payable in OFFSET_SIDES:
            advance = self.ledger.account_role(company_id, role)
            settlement = self._first_account_of_type(company_id, settlement_type)
            if advance is None or settlement is None:
                continue
            balance = counterparty_balance(self.conn, company_id, advance, counterparty_id, day)
            amount = balance if payable else -balance
            if amount <= 0:
                continue
            invoices = [
                i
                for i in open_invoices(
                    self.conn, company_id, counterparty_id, payable=payable, on_date=day
                )
                if not i.source  # only what the books owe
            ]
            paid, _ = allocate(amount, [i.amount for i in invoices])
            parts = tuple((i.invoice, p) for i, p in zip(invoices, paid, strict=True) if p)
            offsets.append(AdvanceOffset(settlement, advance, amount, parts))
        return offsets

    def offset_all_advances(self, company_id: int, day: str, counterparty_id: int) -> list[int]:
        """«Зачесть»: every offset of the plan in one transaction; the documents made."""
        with transaction(self.conn):
            made = [
                self.offset_advances(
                    company_id, day, counterparty_id, o.settlement, o.advance, list(o.parts)
                )
                for o in self.plan_advance_offsets(company_id, day, counterparty_id)
                if o.parts
            ]
        if not made:
            raise ValidationError(tr("нечего зачитывать"))
        return made

    def offset_advances(
        self,
        company_id: int,
        day: str,
        counterparty_id: int,
        settlement_account: int,
        advance_account: int,
        parts: list[tuple[str, int]],
        contract_id: int | None = None,
    ) -> int:
        """An advance set against the e-qaimə that came after it (D78): per e-qaimə,
        paid to a supplier Dt 60.1 [e-qaimə] / Ct 60.2, from a customer Dt 62.2 / Ct 62.1
        [e-qaimə]. The payment itself and its statement stay as they were."""
        parts = [(number, amount) for number, amount in parts if amount]
        if not parts or any(amount < 0 for _, amount in parts):
            raise ValidationError(tr("нечего зачитывать"))
        settlement = self._account(company_id, settlement_account)
        received = settlement["account_type"] == "receivable"
        own = self._partner_subconto(company_id, settlement, counterparty_id, contract_id)
        advance = self._partner_subconto(
            company_id, self._account(company_id, advance_account), counterparty_id, contract_id
        )
        name = self._subconto_value(company_id, counterparty_id)["name"]
        postings = [
            PostingInput(
                advance_account,
                settlement_account,
                from_minor(amount),
                advance,
                own,
                invoice=number,
            )
            if received
            else PostingInput(
                settlement_account,
                advance_account,
                from_minor(amount),
                own,
                advance,
                invoice=number,
            )
            for number, amount in parts
        ]
        return self.ledger.post_new(
            company_id, day, postings, trd("Зачёт аванса: {name}", name=name)
        )

    def _partner_subconto(
        self, company_id: int, account: Row, counterparty_id: int, contract_id: int | None
    ) -> tuple[int | None, ...]:
        """The counterparty and its contract in their positions of the account."""
        kinds = {self._subconto_value(company_id, counterparty_id)["kind_id"]: counterparty_id}
        if contract_id is not None:
            kinds[self._subconto_value(company_id, contract_id)["kind_id"]] = contract_id
        return fill_subconto(account, kinds)
