"""Bank statement files into the bank module: one scenario, one transaction — the lines the
books do not have become bank operations (posted when sure, else drafts that say why), a
conversion between the company's accounts — one conversion of both files' lines, every
day of a file gets the bank's balance. Loading a file again adds nothing: a line is known
by its reference."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace

from modern_gl.application.bank.advances import payment_lines
from modern_gl.application.bank.deposit_import import previous_lines
from modern_gl.application.bank.file_import import (
    CONVERSION,
    FileOperation,
    budget_code,
    file_operations,
    known_references,
    payment_check,
    tax_lines_before,
)
from modern_gl.application.bank.file_links import FileLinkCommands
from modern_gl.application.bank.files import BankFile, BankFileError
from modern_gl.application.bank.import_commands import party_key
from modern_gl.application.bank.imported import DRAFT, KNOWN, LINKED, POSTED, ImportRow
from modern_gl.application.bank.operations import (
    CUSTOMER,
    FEE,
    KIND_TYPES,
    OUT,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    default_memo,
)
from modern_gl.application.bank.places import BankPlace
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED, BANK_FEE
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import dry_run, transaction


@dataclass
class FileImported:
    """What the import did (would do), for the window."""

    posted: int = 0
    drafts: int = 0
    known: int = 0  # loaded before
    linked: int = 0  # typed by hand, got the reference
    counterparties: int = 0  # added to the directory
    closings: int = 0  # days whose balance by the bank was written
    rows: list[ImportRow] = field(default_factory=list)  # in the order of the files


class BankFileCommands(FileLinkCommands):
    def import_bank_files(
        self,
        company_id: int,
        files: Sequence[BankFile],
        places: Mapping[str, BankPlace],
        *,
        take: Collection[str] | None = None,
        post: bool = True,
    ) -> FileImported:
        """Load the files into the bank accounts `places` gives them (IBAN -> account; an
        account without an IBAN keeps the file's); `take` — the references to load (None —
        all), `post` False — the new ones become drafts."""
        with transaction(self.conn):
            return self._import_files(company_id, files, places, take, post)

    def preview_bank_files(
        self, company_id: int, files: Sequence[BankFile], places: Mapping[str, BankPlace]
    ) -> FileImported:
        """What the import would do, nothing written: the import itself, rolled back."""
        with dry_run(self.conn):
            done = self._import_files(company_id, files, places, None, True)
        done.rows = [replace(row, document_id=None) for row in done.rows]
        return done

    def _import_files(
        self,
        company_id: int,
        files: Sequence[BankFile],
        places: Mapping[str, BankPlace],
        take: Collection[str] | None,
        post: bool,
    ) -> FileImported:
        own_tin = self._own_tin(company_id, files)
        for file in files:
            if file.iban in places:
                self._remember_iban(company_id, places[file.iban], file.iban)
        ops = file_operations(files, places, own_tin)
        redo = [op for op in ops if take is None or op.reference in take]
        held, replaced = self._redo_conversion_lines(company_id, redo)
        known = known_references(self.conn, company_id)
        new = [
            op for op in ops if op.reference not in known and (take is None or op.reference in take)
        ]
        links = self._hand_links(company_id, new)
        parties, added = self._import_parties(company_id, links.to_import(new))
        done = FileImported(counterparties=len(added))
        written: set[str] = set()  # this import's: a transfer is in both files
        handled: set[int] = set()  # the other side of a conversion, done with its first
        rows = []
        for op in ops:
            if id(op) in handled:
                continue
            if op.reference in written or (op.reference in known and op.kind != CONVERSION):
                rows.append(ImportRow(op, KNOWN))
                continue
            if take is not None and op.reference not in take:
                continue
            if op.kind == CONVERSION and op.reference in held:
                found = self._held_conversion(op, ops, held[op.reference])
            elif op.kind == CONVERSION:
                found = self._file_conversion(
                    company_id,
                    op,
                    ops,
                    op.reference in known,
                    post,
                    known,
                    replaced.get(op.reference, ()),
                )
            else:
                party = parties.get(party_key(op))
                linked, hold = self._link_hand_typed(company_id, op, links)
                found = [
                    linked or self._file_new(company_id, op, party, party in added, post, hold)
                ]
            handled.update(id(row.op) for row in found)
            written.add(op.reference)
            rows += found
        done.rows = rows
        done.known = sum(1 for row in rows if row.state == KNOWN)
        done.linked = sum(1 for row in rows if row.state == LINKED)
        done.posted = sum(1 for row in rows if row.state == POSTED)
        done.drafts = sum(1 for row in rows if row.state == DRAFT)
        for file in files:
            if file.iban in places:
                done.closings += self._file_closings(company_id, places[file.iban], file)
        return done

    def _own_tin(self, company_id: int, files: Sequence[BankFile]) -> str:
        """The company's VÖEN; a file of another firm's account is not loaded (D113)."""
        mine = self._company(company_id)["tax_id"] or ""
        for file in files:
            if mine and file.owner_tin and file.owner_tin != mine:
                raise BankFileError(
                    tr(
                        "{file}: выписка счёта другой фирмы (VÖEN {theirs}, у компании {mine})",
                        file=file.file_name,
                        theirs=file.owner_tin,
                        mine=mine,
                    )
                )
        return mine or next((f.owner_tin for f in files if f.owner_tin), "")

    def _remember_iban(self, company_id: int, place: BankPlace, iban: str) -> None:
        """The account chosen for a file keeps its IBAN: the next file finds it itself."""
        row = self.conn.execute(
            "SELECT * FROM bank_account_details WHERE company_id = ? AND account_id = ? "
            "AND COALESCE(value_id, 0) = ?",
            (company_id, place.account_id, place.value_id or 0),
        ).fetchone()
        if row is not None and row["iban"]:
            return
        from modern_gl.application.bank.accounts import default_kind

        self.set_bank_account(
            company_id,
            place.account_id,
            place.value_id,
            kind=row["kind"] if row else default_kind(place),
            card_digits=row["card_digits"] if row else "",
            holder_id=row["holder_id"] if row else None,
            iban=iban,
            closed=bool(row["closed"]) if row else False,
        )

    def _file_new(
        self,
        company_id: int,
        op: FileOperation,
        counterparty: int | None,
        new_party: bool,
        post: bool,
        hold: str = "",
    ) -> ImportRow:
        """`hold` — why the line waits as a draft whatever it is (a double?)."""
        data, why = self._file_operation(company_id, op, counterparty, new_party)
        why = hold or why
        # an own account not known is a setting to make, not money nobody knows
        sure_kind = op.kind != TRANSFER and not hold
        unknown = self._to_unidentified(company_id, data) if post and sure_kind else None
        if unknown is not None:  # posted all the same: the bank's balance meets the books
            state, reason, document = self._post_or_draft(company_id, unknown, post)
            if state == POSTED:
                reason = tr("на невыясненных: {why}", why=why)
                self._note_by_document(company_id, document, reason)
            return ImportRow(op, state, self._line_codes(company_id, unknown), reason, document)
        state, reason, document = self._post_or_draft(company_id, data, post, why)
        return ImportRow(op, state, self._line_codes(company_id, data), reason, document)

    def _file_operation(
        self, company_id: int, op: FileOperation, counterparty: int | None, new_party: bool
    ) -> tuple[BankOperationInput, str]:
        """The operation as the line typed in the statement would be, and why it waits
        for the user ("" — it can be posted)."""
        lines, why = self._file_lines(company_id, op, counterparty, new_party)
        name = op.name if counterparty is not None else ""
        data = BankOperationInput(
            doc_date=op.day,
            direction=op.direction,
            account_id=op.place.account_id,
            subconto=op.place.subconto,
            currency_id=op.place.currency_id,
            kind=op.kind,
            counterparty_id=counterparty if op.kind in (SUPPLIER, CUSTOMER) else None,
            lines=tuple(lines),
            memo=op.memo or default_memo(op.direction, op.kind, name),
            reference=op.reference,
        )
        return data, why

    def _file_lines(
        self, company_id: int, op: FileOperation, counterparty: int | None, new_party: bool
    ) -> tuple[list[BankLine], str]:
        unknown = [BankLine(None, op.amount)]
        if op.kind in (SUPPLIER, CUSTOMER):
            return self._payment_lines(company_id, op, counterparty, new_party)
        if op.kind == FEE:  # the settings' account (else as the last fee), «Комиссия банка»
            before = previous_lines(self.conn, company_id, op.place, op, None)
            fee = self.ledger.account_role(company_id, BANK_FEE)
            if fee is None and before:
                fee = before[0].account_id
            if fee is None:
                return unknown, tr("не задан счёт комиссий банка")
            same = before and before[0].account_id == fee
            subconto = before[0].subconto if same else ()
            if not any(subconto):
                subconto = self.named_subconto(company_id, fee, trd("Комиссия банка"))
            return [BankLine(fee, op.amount, subconto)], ""
        if op.kind == TRANSFER:
            if op.target is None:
                return unknown, tr("свой счёт {iban} не найден среди банковских", iban=op.line.iban)
            return [BankLine(op.target.account_id, op.amount, op.target.subconto)], ""
        if op.kind == SALARY:
            before = previous_lines(self.conn, company_id, op.place, op, None)
            account = (
                before[0].account_id
                if before
                else self._first_account_of_type(company_id, KIND_TYPES[SALARY])
            )
            if account is None:
                return unknown, tr("не найден счёт зарплаты")
            return [BankLine(account, op.amount, before[0].subconto if before else ())], ""
        if op.kind == TAX:
            code = budget_code(op.memo)
            before = tax_lines_before(self.conn, company_id, code)
            if before:
                return [replace(before[0], amount=op.amount)], ""
            account = self._first_account_of_type(company_id, KIND_TYPES[TAX])
            why = (
                tr("налог: проверьте счёт (код бюджета {code})", code=code)
                if code
                else tr("налог без кода бюджета — проверьте счёт")
            )
            return [BankLine(account, op.amount)], why
        return unknown, tr("что это — выберите счёт")

    def _payment_lines(
        self, company_id: int, op: FileOperation, counterparty: int | None, new_party: bool
    ) -> tuple[list[BankLine], str]:
        """A supplier's (customer's) payment over the e-qaimə it pays (D78): the account of
        last time, else the first of the kind's type (60, 62)."""
        invoices, why = payment_check(self.conn, company_id, op, counterparty, new_party)
        before = previous_lines(self.conn, company_id, op.place, op, counterparty)
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

    def _file_closings(self, company_id: int, place: BankPlace, file: BankFile) -> int:
        """The bank's balance at the end of every day the file has lines on."""
        closings = {line.day: line.balance for line in file.lines}
        return sum(
            self._import_closing(company_id, place, day, amount, "file")
            for day, amount in sorted(closings.items())
        )
