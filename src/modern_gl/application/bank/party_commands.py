"""A payment's lines over what it pays, and the drafts that wait for a counterparty: a
line of a bank's file whose sender the directory lacked finds the counterparty once it is
there — an e-qaimə brought it, a person added it — and is spread over its unpaid e-qaimə
as the import would have done. It stays a draft: a person checks it."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from modern_gl.application.bank.advances import payment_lines
from modern_gl.application.bank.deposit_import import invoices_in
from modern_gl.application.bank.file_import import Payment, payment_check
from modern_gl.application.bank.import_commands import BankImportCommands
from modern_gl.application.bank.operations import (
    CUSTOMER,
    KIND_TYPES,
    OUT,
    SUPPLIER,
    BankLine,
    BankOperation,
    BankOperationInput,
    last_lines,
    load_bank_operations,
)
from modern_gl.application.bank.parties import statement_party
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


@dataclass(frozen=True)
class WaitingPayment:
    """A draft loaded from a file, as the file's line was: what `payment_check` reads."""

    op: BankOperation

    @property
    def day(self) -> str:
        return self.op.doc_date

    @property
    def direction(self) -> str:
        return self.op.direction

    @property
    def amount(self) -> int:
        return self.op.total

    @property
    def kind(self) -> str:
        return self.op.kind

    @property
    def pays_vat(self) -> bool:
        return any(line.pays_vat for line in self.op.lines)

    @property
    def invoices(self) -> tuple[tuple[str, int | None], ...]:
        return tuple((number, None) for number in invoices_in(self.op.memo))


class BankPartyCommands(BankImportCommands):
    def adopt_parties(self, company_id: int) -> int:
        """The drafts that wait for a counterparty (loaded from a file, not touched by a
        person since) get the one found now by the sender's VÖEN or name. How many."""
        with transaction(self.conn):
            return self._adopt_parties(company_id)

    def _adopt_parties(self, company_id: int) -> int:
        ids = [
            r["id"]
            for r in self.conn.execute(
                "SELECT o.id FROM bank_operations o "
                "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
                "WHERE o.company_id = ? AND d.status = 'draft' AND o.counterparty_id IS NULL "
                "AND o.kind IN (?, ?) AND o.note <> '' "
                "AND (o.party_tin <> '' OR o.party_name <> '') "
                "ORDER BY d.doc_date, d.number",
                (company_id, SUPPLIER, CUSTOMER),
            )
        ]
        waiting = load_bank_operations(self.conn, company_id, ids)
        found: dict[tuple[str, str], int | None] = {}
        adopted = 0
        for operation_id in ids:
            op = waiting[operation_id]
            sender = (op.party_tin, op.party_name)
            if sender not in found:
                found[sender] = statement_party(self.conn, company_id, *sender)
            party = found[sender]
            if party is None:
                continue
            lines, why = self._payment_lines(company_id, WaitingPayment(op), party)
            data = BankOperationInput(
                **{f.name: getattr(op, f.name) for f in fields(BankOperationInput)}
            )
            data = replace(data, counterparty_id=party, lines=tuple(lines))
            self.save_bank_operation(company_id, data, operation_id, post=False)
            self._set_note(company_id, operation_id, why)
            adopted += 1
        return adopted

    def _payment_lines(
        self, company_id: int, op: Payment, counterparty: int | None, waits: str = ""
    ) -> tuple[list[BankLine], str]:
        """A supplier's (customer's) payment over the e-qaimə it pays (D78): the account of
        last time, else the first of the kind's type (60, 62); `waits` — why it is not
        posted whatever it pays. Without a counterparty — the account alone: nobody
        else's subconto."""
        invoices, why = payment_check(self.conn, company_id, op, counterparty, waits)
        before = (
            last_lines(self.conn, company_id, op.direction, counterparty)
            if counterparty is not None
            else []
        )
        account = (
            before[0].account_id
            if before
            else self._first_account_of_type(company_id, KIND_TYPES[op.kind])
        )
        if account is None:
            return [BankLine(None, op.amount)], tr("не найден счёт расчётов")
        role = ADVANCE_PAID if op.direction == OUT else ADVANCE_RECEIVED
        lines = payment_lines(
            self.conn,
            company_id,
            account_id=account,
            account_type=self._account(company_id, account)["account_type"],
            subconto=before[0].subconto if before else (),
            counterparty_id=counterparty,
            amount=op.amount,
            direction=op.direction,
            day=op.day,
            invoices=invoices,
            # the ƏDV paid ahead stays on the settlement account (D145)
            advance_account=None if op.pays_vat else self.ledger.account_role(company_id, role),
        )
        if op.pays_vat:
            lines = [replace(line, pays_vat=True) for line in lines]
        return lines, why
