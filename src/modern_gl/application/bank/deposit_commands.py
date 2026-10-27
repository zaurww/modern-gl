"""The ƏDV deposit account's statement from the tax portal (D112): one scenario, one
transaction — the operations the books do not have become bank operations (posted when
everything is known, else drafts: «не разнесены»), those entered by hand get their
reference, every day gets the balance by the portal."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace

from modern_gl.application.bank.advances import payment_lines
from modern_gl.application.bank.deposit_import import (
    DepositOperation,
    day_closings,
    plan_deposit_import,
    previous_lines,
)
from modern_gl.application.bank.deposit_reconciliation import (
    DepositReconciliation,
    books_figures,
)
from modern_gl.application.bank.import_commands import BankImportCommands, party_key
from modern_gl.application.bank.imported import KNOWN, LINKED, POSTED, ImportRow
from modern_gl.application.bank.operations import (
    KIND_TYPES,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    default_memo,
)
from modern_gl.application.bank.places import BankPlace
from modern_gl.application.common import now
from modern_gl.domain.accounts import OUTPUT_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import dry_run, transaction


@dataclass
class DepositImported:
    """What the import did, for the message after it."""

    posted: int = 0
    drafts: list[tuple[DepositOperation, str]] = field(default_factory=list)  # and why
    linked: int = 0  # entered by hand, now marked as the portal's
    known: int = 0  # loaded before
    counterparties: int = 0  # added to the directory by VÖEN
    closings: int = 0  # days whose balance by the portal was written
    rows: list[ImportRow] = field(default_factory=list)  # in the order of the portal


class VatDepositCommands(BankImportCommands):
    def import_vat_deposit(
        self,
        company_id: int,
        place: BankPlace,
        operations: Sequence[DepositOperation],
        balance: int,
        period: tuple[str, str] | None = None,
        *,
        take: Collection[str] | None = None,
        post: bool = True,
    ) -> DepositImported:
        """Load the portal's operations into the deposit account: `operations` — from a day
        up to now, `balance` — the account's balance by the portal now; `period` — the
        days to load (the later operations only count the balance back), remembered as
        loaded (D115) unless `take` (the references to load; None — all) left one out;
        `post` False — the new ones become drafts. Loading again adds nothing."""
        with transaction(self.conn):
            return self._import_deposit(company_id, place, operations, balance, period, take, post)

    def preview_vat_deposit(
        self,
        company_id: int,
        place: BankPlace,
        operations: Sequence[DepositOperation],
        balance: int,
        period: tuple[str, str] | None = None,
    ) -> DepositImported:
        """What the import would do, nothing written: the import itself, rolled back — the
        preview and the import cannot differ."""
        with dry_run(self.conn):
            done = self._import_deposit(company_id, place, operations, balance, period)
        done.rows = [replace(row, document_id=None) for row in done.rows]
        return done

    def _import_deposit(
        self,
        company_id: int,
        place: BankPlace,
        operations: Sequence[DepositOperation],
        balance: int,
        period: tuple[str, str] | None,
        take: Collection[str] | None = None,
        post: bool = True,
    ) -> DepositImported:
        done = DepositImported()
        closings = day_closings(operations, balance)
        if period is not None:
            first, last = period
            operations = [op for op in operations if first <= op.day <= last]
            closings = {day: n for day, n in closings.items() if first <= day <= last}
        plan = plan_deposit_import(self.conn, company_id, place, operations)
        done.known = len(plan.known)
        rows = [ImportRow(op, KNOWN) for op in plan.known]
        taken = [x for x in plan.linked if take is None or x[0].reference in take]
        for op, operation_id in taken:
            self.conn.execute(
                "UPDATE bank_operations SET reference = ? WHERE company_id = ? AND id = ?",
                (op.reference, company_id, operation_id),
            )
            self._audit(company_id, "bank_operation", operation_id, "update", {"reference": ""})
            document = self._bank_row(company_id, operation_id)["document_id"]
            rows.append(ImportRow(op, LINKED, document_id=document))
            done.linked += 1
        new = [op for op in plan.new if take is None or op.reference in take]
        parties, added = self._import_parties(company_id, new)
        done.counterparties = len(added)
        rows += [
            self._deposit_new(company_id, place, x, parties.get(party_key(x)), post, done)
            for x in new
        ]
        for day, amount in sorted(closings.items()):
            done.closings += self._import_closing(company_id, place, day, amount, "api")
        if period is not None and len(taken) + len(new) == len(plan.linked) + len(plan.new):
            self._remember_load(company_id, place, period, operations)
        moments = {id(op): op.moment for op in operations}
        done.rows = sorted(rows, key=lambda row: moments[id(row.op)])
        return done

    def _deposit_new(
        self,
        company_id: int,
        place: BankPlace,
        op: DepositOperation,
        counterparty: int | None,
        post: bool,
        done: DepositImported,
    ) -> ImportRow:
        """A new operation posted (a draft, when posting fails — and why)."""
        data = self._deposit_operation(company_id, place, op, counterparty)
        state, reason, document = self._post_or_draft(company_id, data, post)
        if state == POSTED:
            done.posted += 1
        else:
            done.drafts.append((op, reason))
        return ImportRow(op, state, self._line_codes(company_id, data), reason, document)

    def mark_deposit_reconciled(
        self, company_id: int, place: BankPlace, seen: DepositReconciliation
    ) -> None:
        """The period reconciled with the portal (D118): the portal's figures as seen, the
        books' as they are now; marked again — the new ones."""
        first, last = seen.date_from, seen.date_to
        if last < first:
            raise ValidationError(tr("начало периода позже конца"))
        books = books_figures(self.conn, company_id, place, first, last)
        key = (company_id, place.account_id, place.value_id or 0, first, last)
        with transaction(self.conn):
            self.conn.execute(
                "DELETE FROM bank_portal_reconciled WHERE company_id = ? AND account_id = ? "
                "AND COALESCE(value_id, 0) = ? AND date_from = ? AND date_to = ?",
                key,
            )
            self.conn.execute(
                "INSERT INTO bank_portal_reconciled (company_id, account_id, value_id, "
                "date_from, date_to, reconciled_at, portal_opening, portal_in, portal_out, "
                "books_opening, books_in, books_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    company_id,
                    place.account_id,
                    place.value_id,
                    first,
                    last,
                    now(),
                    seen.portal.opening,
                    seen.portal.money_in,
                    seen.portal.money_out,
                    books.opening,
                    books.money_in,
                    books.money_out,
                ),
            )

    def _remember_load(
        self,
        company_id: int,
        place: BankPlace,
        period: tuple[str, str],
        operations: Sequence[DepositOperation],
    ) -> None:
        first, last = period
        if last < first:
            raise ValidationError(tr("начало периода позже конца"))
        self.conn.execute(
            "INSERT INTO bank_portal_loads (company_id, account_id, value_id, date_from, "
            "date_to, loaded_at, operations) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                place.account_id,
                place.value_id,
                first,
                last,
                now(),
                sum(1 for op in operations if op.done),
            ),
        )

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
            account = self.ledger.account_role(company_id, OUTPUT_VAT)
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
