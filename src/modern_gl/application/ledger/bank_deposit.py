"""The ƏDV deposit account's statement from the tax portal (D110): one scenario, one
transaction — the operations the books do not have become bank operations (posted when
everything is known, else drafts: «не разнесены»), those entered by hand get their
reference, every day gets the balance by the portal."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.bank import (
    CUSTOMER,
    KIND_TYPES,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    BankPlace,
    default_memo,
    payment_lines,
)
from modern_gl.application.bank.deposit_import import (
    DepositOperation,
    day_closings,
    plan_deposit_import,
    previous_lines,
)
from modern_gl.application.counterparties import known_counterparty, short_name
from modern_gl.application.ledger.bank import BankCommands
from modern_gl.application.ledger.bank_statements import BankStatementCommands
from modern_gl.domain.accounts import OUTPUT_VAT
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import transaction


@dataclass
class DepositImported:
    """What the import did, for the message after it."""

    posted: int = 0
    drafts: list[tuple[DepositOperation, str]] = field(default_factory=list)  # and why
    linked: int = 0  # entered by hand, now marked as the portal's
    known: int = 0  # loaded before
    counterparties: int = 0  # added to the directory by VÖEN
    closings: int = 0  # days whose balance by the portal was written


class VatDepositCommands(BankCommands, BankStatementCommands):
    def import_vat_deposit(
        self,
        company_id: int,
        place: BankPlace,
        operations: Sequence[DepositOperation],
        balance: int,
    ) -> DepositImported:
        """Load the portal's operations of a period up to now into the deposit account;
        `balance` — the account's balance by the portal now. Loading again adds nothing."""
        done = DepositImported()
        with transaction(self.conn):
            plan = plan_deposit_import(self.conn, company_id, place, operations)
            done.known = len(plan.known)
            for op, operation_id in plan.linked:
                self.conn.execute(
                    "UPDATE bank_operations SET reference = ? WHERE company_id = ? AND id = ?",
                    (op.reference, company_id, operation_id),
                )
                self._audit(company_id, "bank_operation", operation_id, "update", {"reference": ""})
                done.linked += 1
            parties = self._deposit_parties(company_id, plan.new, done)
            for op in plan.new:
                data = self._deposit_operation(company_id, place, op, parties.get(op.tin))
                self.conn.execute("SAVEPOINT deposit_operation")
                try:
                    self.save_bank_operation(company_id, data, post=True)
                    done.posted += 1
                except LedgerError as e:
                    self.conn.execute("ROLLBACK TO deposit_operation")
                    self.save_bank_operation(company_id, data, post=False)
                    done.drafts.append((op, str(e)))
                self.conn.execute("RELEASE deposit_operation")
            for day, amount in sorted(day_closings(operations, balance).items()):
                done.closings += self._deposit_closing(company_id, place, day, amount)
        return done

    def _deposit_parties(
        self, company_id: int, operations: Sequence[DepositOperation], done: DepositImported
    ) -> dict[str, int]:
        """VÖEN -> counterparty; one the company does not have is added with a shorter
        name (as the e-qaimə import suggests it) and the portal's name as the legal one."""
        found: dict[str, int] = {}
        kind = None
        for op in operations:
            if op.kind not in (SUPPLIER, CUSTOMER) or not op.tin or op.tin in found:
                continue
            existing = known_counterparty(self.conn, company_id, op.tin, op.name)
            if existing is None:
                kind = kind or self.subconto_kind_id(company_id, "counterparty")
                existing = self.add_subconto_value(company_id, kind, short_name(op.name))
                self.set_subconto_value_tax(company_id, existing, op.tin)
                self.set_subconto_value_legal_name(company_id, existing, op.name)
                done.counterparties += 1
            found[op.tin] = existing
        return found

    def _deposit_operation(
        self, company_id: int, place: BankPlace, op: DepositOperation, counterparty: int | None
    ) -> BankOperationInput:
        """The operation as the line typed in the statement would be: the account of last
        time (else 68.2 ƏDV by its role, the first account of the kind's type: 60, 62), the
        ƏDV over the e-qaimə named, oldest first. A transfer from the company's bank:
        which bank — the user says (a draft)."""
        before = previous_lines(self.conn, company_id, place, op, counterparty)
        account, subconto = (before[0].account_id, before[0].subconto) if before else (None, ())
        if account is None and op.kind == TAX:  # the deposit pays the budget only ƏDV
            account = self.account_role(company_id, OUTPUT_VAT)
        if account is None and op.kind != TRANSFER:
            account = self._first_account_of_type(company_id, KIND_TYPES[op.kind])
        if account is None:
            number = op.invoices[0][0] if len(op.invoices) == 1 else ""
            lines = [BankLine(None, op.amount, (), number)]
        else:
            lines = payment_lines(
                self.conn,
                company_id,
                account_id=account,
                account_type=self._account(company_id, account)["account_type"],
                subconto=subconto,
                counterparty_id=counterparty,
                amount=op.amount,
                direction=op.direction,
                day=op.day,
                invoices=op.invoices,
            )
        name = op.name if counterparty is not None else ""
        return BankOperationInput(
            doc_date=op.day,
            direction=op.direction,
            account_id=place.account_id,
            subconto=place.subconto,
            kind=op.kind,
            counterparty_id=counterparty,
            lines=tuple(lines),
            memo=op.memo or default_memo(op.direction, op.kind, name),
            reference=op.reference,
        )

    def _deposit_closing(self, company_id: int, place: BankPlace, day: str, amount: int) -> int:
        """The balance by the portal at the end of the day, on the day's statement or on
        the period's that ends that day (a period that ends later: nothing to compare)."""
        covering = self.conn.execute(
            "SELECT date_from, date_to FROM bank_statements WHERE company_id = ? "
            "AND account_id = ? AND COALESCE(value_id, 0) = ? AND date_from <= ? "
            "AND date_to >= ?",
            (company_id, place.account_id, place.value_id or 0, day, day),
        ).fetchone()
        start, end = (covering["date_from"], covering["date_to"]) if covering else (day, day)
        if end != day:
            return 0
        statement_id = self.set_bank_closing(
            company_id, place.account_id, place.value_id, start, end, amount
        )
        if covering is None:
            self.conn.execute(
                "UPDATE bank_statements SET source = 'api' WHERE company_id = ? AND id = ?",
                (company_id, statement_id),
            )
        return 1
