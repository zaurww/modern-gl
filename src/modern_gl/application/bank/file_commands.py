"""Bank statement files into the bank module: one scenario, one transaction — the lines the
books do not have become bank operations (posted when sure, else drafts that say why), a
conversion between the company's accounts — one conversion of both files' lines, every
day of a file gets the bank's balance. Loading a file again adds nothing: a line is known
by its reference. A file adds no counterparty: a sender the directory lacks waits as a
draft with the bank's VÖEN and name (`parties`, `party_commands`)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace

from modern_gl.application.bank.deposit_import import previous_lines
from modern_gl.application.bank.file_import import (
    CONVERSION,
    FileOperation,
    book_key,
    budget_code,
    file_operations,
    iban_places,
    lines_in_books,
    tax_lines_before,
)
from modern_gl.application.bank.file_links import FileLinkCommands
from modern_gl.application.bank.files import BankFile, BankFileError
from modern_gl.application.bank.import_commands import party_key
from modern_gl.application.bank.imported import (
    DRAFT,
    KNOWN,
    LINKED,
    POSTED,
    SKIPPED,
    ImportRow,
)
from modern_gl.application.bank.operations import (
    CUSTOMER,
    FEE,
    KIND_TYPES,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
    default_memo,
    load_bank_operation,
)
from modern_gl.application.bank.parties import statement_party, unknown_party_text
from modern_gl.application.bank.places import BankPlace
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import dry_run, transaction


@dataclass
class FileImported:
    """What the import did (would do), for the window."""

    posted: int = 0
    drafts: int = 0
    known: int = 0  # loaded before
    linked: int = 0  # typed by hand, got the reference
    unknown_parties: int = 0  # senders the directory lacks: their lines wait
    closings: int = 0  # days whose balance by the bank was written
    skipped: int = 0  # lines of the files left out of the books (why — in the rows)
    rows: list[ImportRow] = field(default_factory=list)  # in the order of the files


def _left_out(
    ops: Sequence[FileOperation], rows: Sequence[ImportRow], chosen: bool
) -> list[ImportRow]:
    """A row for every line of the files the import said nothing of: no line of a
    statement goes unsaid — it is in the books, or the window says why it is not (the
    fee of a conversion in the books already is in it)."""
    said = {(row.op.reference, getattr(row.op, "place", None)): row.state for row in rows}
    why = tr("галочка снята") if chosen else tr("программа не узнала строку")
    found = []
    for op in ops:
        if (op.reference, op.place) not in said:
            found.append(ImportRow(op, SKIPPED, (), why))
        known = said.get((op.reference, op.place)) == KNOWN
        found += [
            ImportRow(FileOperation(fee, op.place, FEE), KNOWN)
            if known
            else ImportRow(FileOperation(fee, op.place, FEE), SKIPPED, (), why)
            for fee in op.fees
            if (fee.reference, op.place) not in said
        ]
    return found


def _as_input(op: BankOperationInput) -> BankOperationInput:
    """The operation as typed (a loaded one written again)."""
    names = BankOperationInput.__dataclass_fields__
    return BankOperationInput(**{name: getattr(op, name) for name in names})


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
        # every account known by its IBAN: the other side of a transfer or a conversion
        # is found when one file is loaded alone
        ops = file_operations(files, places, own_tin, iban_places(self.conn, company_id))
        redo = [op for op in ops if take is None or op.reference in take]
        held, replaced, gone = self._redo_conversion_lines(company_id, redo)
        known = lines_in_books(self.conn, company_id)
        references = {key[0] for key in known}
        new = [
            op for op in ops if book_key(op) not in known and (take is None or op.reference in take)
        ]
        links = self._hand_links(company_id, new)
        self._adopt_parties(company_id)  # the drafts of earlier files: found meanwhile?
        parties, unknown = self._file_parties(company_id, links.to_import(new))
        done = FileImported(unknown_parties=len(unknown))
        written: set[str] = set()  # this import's: a transfer is in both files
        handled: set[int] = set()  # the other side of a conversion, done with its first
        rows = []
        for op in ops:
            if id(op) in handled:
                continue
            if op.reference in written or (book_key(op) in known and op.kind != CONVERSION):
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
                    post,
                    references,
                    replaced.get(op.reference, ()),
                    gone.get(op.reference, ()),
                )
            elif op.reference in references:  # the other account's line of a transfer
                found = [self._file_other_side(company_id, op, post)]
            else:
                party = parties.get(party_key(op))
                linked, hold = self._link_hand_typed(company_id, op, links)
                found = [linked or self._file_new(company_id, op, party, post, hold)]
            handled.update(id(row.op) for row in found)
            written.add(op.reference)
            rows += found
        done.rows = rows + _left_out(ops, rows, take is not None)
        done.skipped = sum(1 for row in done.rows if row.state == SKIPPED)
        rows = done.rows
        done.known = sum(1 for row in rows if row.state == KNOWN)
        done.linked = sum(1 for row in rows if row.state == LINKED)
        done.posted = sum(1 for row in rows if row.state == POSTED)
        done.drafts = sum(1 for row in rows if row.state == DRAFT)
        for file in files:
            if file.iban in places:
                done.closings += self._file_closings(company_id, places[file.iban], file)
        return done

    def _file_other_side(self, company_id: int, op: FileOperation, post: bool) -> ImportRow:
        """A transfer between the company's accounts whose other account's line is in the
        books already — as an operation that does not come to this account (loaded while
        this account was not known; posted by hand onto 57): this account's line is not
        there yet. The other one waits for its account — it gets this one; it went
        elsewhere — this line goes to the same account (57 closes), a draft that says so."""
        row = self.conn.execute(
            "SELECT o.id, d.number FROM bank_operations o "
            "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
            "WHERE o.company_id = ? AND o.reference = ? ORDER BY d.number LIMIT 1",
            (company_id, op.reference),
        ).fetchone()
        other = load_bank_operation(self.conn, company_id, row["id"])
        waits = len(other.lines) == 1 and other.lines[0].account_id is None
        if waits and other.status == "draft" and other.direction != op.direction:
            line = replace(
                other.lines[0], account_id=op.place.account_id, subconto=op.place.subconto
            )
            data = _as_input(replace(other, kind=TRANSFER, lines=(line,)))
            self.delete_bank_operation(company_id, other.id)
            state, why, document = self._post_or_draft(company_id, data, post)
            return ImportRow(op, state, self._line_codes(company_id, data), why, document)
        data, _ = self._file_operation(company_id, op, None)
        lines = tuple(replace(x, amount=op.amount) for x in other.lines[:1])
        data = replace(data, lines=lines)
        why = tr(
            "другая сторона перевода — операция №{n}: проверьте счёт и проведите", n=row["number"]
        )
        state, why, document = self._post_or_draft(company_id, data, False, why)
        return ImportRow(op, state, self._line_codes(company_id, data), why, document)

    def _file_parties(
        self, company_id: int, ops: Sequence[FileOperation]
    ) -> tuple[dict[str, int], set[str]]:
        """`party_key` -> the counterparty of the suppliers and customers found (by the
        VÖEN, the name, as last time), and the keys of those the directory lacks: the file
        adds none — the bank's spelling is not a name."""
        found: dict[str, int] = {}
        unknown: set[str] = set()
        for op in ops:
            key = party_key(op)
            if op.kind not in (SUPPLIER, CUSTOMER) or not key or key in found or key in unknown:
                continue
            party = statement_party(self.conn, company_id, op.tin, op.name)
            if party is None:
                unknown.add(key)
            else:
                found[key] = party
        return found, unknown

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
        if (row is not None and row["iban"]) or place.is_cash:  # a cash desk has no details
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
        post: bool,
        hold: str = "",
    ) -> ImportRow:
        """`hold` — why the line waits as a draft whatever it is (a double?)."""
        data, why = self._file_operation(company_id, op, counterparty)
        why = hold or why
        # an own account not known is a setting to make, not money nobody knows
        # a tax is known for what it is: it waits for its account, not among the unknown
        sure_kind = op.kind not in (TRANSFER, TAX) and not hold
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
        self, company_id: int, op: FileOperation, counterparty: int | None
    ) -> tuple[BankOperationInput, str]:
        """The operation as the line typed in the statement would be, and why it waits
        for the user ("" — it can be posted). A payment keeps whom the bank names."""
        lines, why = self._file_lines(company_id, op, counterparty)
        name = op.name if counterparty is not None else ""
        payment = op.kind in (SUPPLIER, CUSTOMER)
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
            party_tin=op.tin if payment else "",
            party_name=op.name if payment else "",
        )
        return data, why

    def _file_lines(
        self, company_id: int, op: FileOperation, counterparty: int | None
    ) -> tuple[list[BankLine], str]:
        unknown = [BankLine(None, op.amount)]
        if op.kind in (SUPPLIER, CUSTOMER):
            waits = "" if counterparty is not None else unknown_party_text(op.tin, op.name)
            return self._payment_lines(company_id, op, counterparty, waits)
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
            # which tax (68.1, 68.2, 69…) — only the user knows: no guess to post by mistake
            account = self._only_account_of_type(company_id, KIND_TYPES[TAX])
            why = (
                tr("налог: выберите счёт (код бюджета {code})", code=code)
                if code
                else tr("налог без кода бюджета — выберите счёт")
            )
            return [BankLine(account, op.amount)], why
        return unknown, tr("что это — выберите счёт")

    def _file_closings(self, company_id: int, place: BankPlace, file: BankFile) -> int:
        """The bank's balance at the end of every day the file has lines on."""
        closings = {line.day: line.balance for line in file.lines}
        return sum(
            self._import_closing(company_id, place, day, amount, "file")
            for day, amount in sorted(closings.items())
        )
