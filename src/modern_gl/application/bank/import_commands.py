"""What every import into a bank account does the same way — the tax portal's ƏDV deposit
(D112), a bank's statement file: counterparties found (or added) by VÖEN, an operation
posted when it can be (a draft when posting fails — and why), the bank's balance at the
end of a day written on the day's statement."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from modern_gl.application.bank.account_commands import BankStatementCommands
from modern_gl.application.bank.commands import BankCommands
from modern_gl.application.bank.imported import DRAFT, POSTED, ImportedOperation
from modern_gl.application.bank.operations import (
    CUSTOMER,
    OTHER,
    SUPPLIER,
    BankOperationInput,
)
from modern_gl.application.bank.places import BankPlace
from modern_gl.application.counterparties import known_counterparty, short_name
from modern_gl.domain.accounts import UNIDENTIFIED
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import fold, tr, trd
from modern_gl.infrastructure.db import transaction


def party_key(op: ImportedOperation) -> str:
    """How the import knows the other side: its VÖEN, else (abroad) its name."""
    return op.tin or fold(" ".join(op.name.split()))


class BankImportCommands(BankCommands, BankStatementCommands):
    def _import_parties(
        self, company_id: int, operations: Iterable[ImportedOperation]
    ) -> tuple[dict[str, int], set[int]]:
        """`party_key` -> counterparty of the suppliers and customers, and the ones added:
        one the company does not have is added with a shorter name (as the e-qaimə import
        suggests it) and the full name as the legal one."""
        found: dict[str, int] = {}
        added: set[int] = set()
        kind = None
        for op in operations:
            key = party_key(op)
            if op.kind not in (SUPPLIER, CUSTOMER) or not key or key in found:
                continue
            existing = known_counterparty(self.conn, company_id, op.tin, op.name)
            if existing is None:
                kind = kind or self.ledger.subconto_kind_id(company_id, "counterparty")
                existing = self.ledger.add_subconto_value(company_id, kind, short_name(op.name))
                if op.tin:
                    self.ledger.set_subconto_value_tax(company_id, existing, op.tin)
                self.ledger.set_subconto_value_legal_name(company_id, existing, op.name)
                added.add(existing)
            found[key] = existing
        return found, added

    def move_fees_to(self, company_id: int, fee_account: int) -> int:
        """The fees of the open period on other accounts go to `fee_account` (loaded before
        the settings named it): each keeps its number and status — all or none. How many."""
        from modern_gl.application.bank.fee_moves import fees_elsewhere

        with transaction(self.conn):
            return sum(
                self.change_line_account(company_id, ids, old, fee_account)
                for old, ids in fees_elsewhere(self.conn, company_id, fee_account).items()
            )

    def unidentified_account(self, company_id: int) -> int:
        """The account of what nobody knows yet (D184): the settings' one; a
        company without it gets «76.9 Невыясненные поступления и списания» — under 76 when
        that is a group, without a code when 76.9 is taken — and keeps it in the settings."""
        found = self.ledger.account_role(company_id, UNIDENTIFIED)
        if found is not None:
            return found
        taken = self.conn.execute(
            "SELECT code, is_group FROM accounts WHERE company_id = ? AND code IN ('76', '76.9')",
            (company_id,),
        ).fetchall()
        codes = {r["code"]: r["is_group"] for r in taken}
        made = self.ledger.add_account(
            company_id,
            None if "76.9" in codes else "76.9",
            trd("Невыясненные поступления и списания"),
            parent="76" if codes.get("76") else None,
            account_type="other_liability",
            two_sided=True,
        )
        self.ledger.set_account_role(company_id, UNIDENTIFIED, made)
        return made

    def _to_unidentified(
        self, company_id: int, data: BankOperationInput
    ) -> BankOperationInput | None:
        """The lines whose account is not known go to the unidentified account; None —
        every line has its account."""
        if all(x.account_id is not None for x in data.lines):
            return None
        account = self.unidentified_account(company_id)
        lines = tuple(
            replace(x, account_id=account, subconto=()) if x.account_id is None else x
            for x in data.lines
        )
        return replace(data, kind=OTHER, lines=lines)

    def _post_or_draft(
        self, company_id: int, data: BankOperationInput, post: bool, why: str = ""
    ) -> tuple[str, str, int]:
        """The operation saved: posted when `post` and nothing `why` not to, else (and
        when posting fails) a draft. -> (POSTED or DRAFT, why a draft, its GL document)."""
        if post and not why:
            try:
                with transaction(self.conn):  # a savepoint: what did not post is undone
                    saved = self.save_bank_operation(company_id, data, post=True)
                return POSTED, "", self._bank_row(company_id, saved)["document_id"]
            except LedgerError as e:
                why = str(e)
        saved = self.save_bank_operation(company_id, data, post=False)
        return (
            DRAFT,
            why or tr("загружено черновиком"),
            self._bank_row(company_id, saved)["document_id"],
        )

    def _line_codes(
        self, company_id: int, data: BankOperationInput
    ) -> tuple[tuple[str, str, int], ...]:
        """(account's code, e-qaimə, amount) of each line: what the operation becomes."""
        return tuple(
            (
                self._account(company_id, x.account_id)["code"] if x.account_id else "",
                x.invoice,
                x.amount,
            )
            for x in data.lines
        )

    def _import_closing(
        self, company_id: int, place: BankPlace, day: str, amount: int, source: str
    ) -> int:
        """The bank's balance at the end of the day, on the day's statement or on the
        period's that ends that day (a period that ends later: nothing to compare); a new
        statement is marked as the `source`'s ('api', 'file')."""
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
                "UPDATE bank_statements SET source = ? WHERE company_id = ? AND id = ?",
                (source, company_id, statement_id),
            )
        return 1
