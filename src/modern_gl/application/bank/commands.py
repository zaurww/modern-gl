"""Bank operations (D47): money in or out of one bank account, a document that builds its
own GL postings.

Məxaric (out): Dt the line's account [its subconto] / Ct the bank account — per line;
mədaxil (in): Dt the bank account / Ct the line's account. The purpose of payment is the
memo, the line's e-qaimə goes into its posting (it closes the e-qaimə in the report,
D38). An operation in a currency: each line at the Central Bank's rate of the day, the
amount in the currency kept on the posting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import date

from modern_gl.application.bank.advances import AdvanceOffset, counterparty_balance
from modern_gl.application.bank.operations import (
    FEE,
    IN,
    KIND_NAMES,
    OUT,
    VAT_DEPOSIT_KINDS,
    BankLine,
    BankOperation,
    BankOperationInput,
    allocate,
    load_bank_operations,
)
from modern_gl.application.common import account_kinds, fill_subconto, pad_subconto
from modern_gl.application.currencies import no_rate_text, rate_on
from modern_gl.application.invoices import open_invoices
from modern_gl.application.ledger.documents import explain_owner
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.module import ModuleBase
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.domain.currency import to_base
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.db import Row, transaction

# (the settlement account's type, the advance's role, the company owes the e-qaimə)
OFFSET_SIDES = (("payable", ADVANCE_PAID, True), ("receivable", ADVANCE_RECEIVED, False))

explain_owner(
    "bank",
    lambda _role, _n, _m: tr(
        "проводки созданы банковской операцией; исправьте её в разделе «Банк»"
    ),
)


class BankCommands(ModuleBase):
    def save_bank_payment(
        self,
        company_id: int,
        data: BankOperationInput,
        deposit: BankOperationInput | None,
        *,
        post: bool,
        checked: bool | None = None,
    ) -> list[int]:
        """A new payment and its ƏDV part on the ƏDV deposit account (D69): two
        operations, each on its own account, saved both or neither."""
        with transaction(self.conn):
            saved = [self.save_bank_operation(company_id, data, post=post, checked=checked)]
            if deposit is not None:
                saved.append(
                    self.save_bank_operation(company_id, deposit, post=post, checked=checked)
                )
        return saved

    def save_bank_operation(
        self,
        company_id: int,
        data: BankOperationInput,
        operation_id: int | None = None,
        *,
        post: bool,
        checked: bool | None = None,
    ) -> int:
        """Create or change a bank operation; `post` builds and posts its GL document.

        A posted operation is changed in place (D32): its document keeps the number.
        A draft keeps only what was entered — its GL document has no postings yet.
        `checked` — a person saved it (the form, the statement's line); None keeps it.
        """
        self._check_bank_input(company_id, data)
        with transaction(self.conn):
            if operation_id is None:
                doc_id = self.documents.new(company_id, data.doc_date, data.memo)
                saved: int = self.conn.execute(
                    "INSERT INTO bank_operations (company_id, document_id, direction) "
                    "VALUES (?, ?, ?) RETURNING id",
                    (company_id, doc_id, data.direction),
                ).fetchone()[0]
                action = "create"
            else:
                saved = operation_id
                row = self._bank_row(company_id, saved)
                doc = self.documents.get(company_id, row["document_id"])
                if doc["status"] == "posted":
                    if not post:
                        raise ValidationError(
                            tr(
                                "документ №{n} проведён: чтобы сохранить его черновиком, "
                                "сначала отмените проведение",
                                n=doc["number"],
                            )
                        )
                    self.documents.require_changeable(company_id, doc)
                doc_id = row["document_id"]
                action = "update"
            self._store_bank(company_id, saved, data)
            if checked is not None:
                self._set_checked(company_id, saved, checked and post)
            if checked:  # a person saved it: the import's note is read
                self._set_note(company_id, saved, "")
            if post:
                postings = self._bank_postings(company_id, data)
                self.documents.write(company_id, doc_id, data.doc_date, postings, data.memo)
                action = "post"
            else:
                self.documents.set_header(company_id, doc_id, data.doc_date, data.memo)
            self._audit(company_id, "bank_operation", saved, action, {})
        return saved

    def unpost_bank_operation(self, company_id: int, operation_id: int) -> None:
        """Back to a draft: its postings go (the audit trail keeps them)."""
        with transaction(self.conn):
            row = self._bank_row(company_id, operation_id)
            self.documents.unpost(company_id, self.documents.get(company_id, row["document_id"]))
            self._set_checked(company_id, operation_id, False)
            self._audit(company_id, "bank_operation", operation_id, "unpost", {})

    def delete_bank_operation(self, company_id: int, operation_id: int) -> None:
        with transaction(self.conn):
            row = self._bank_row(company_id, operation_id)
            doc = self.documents.get(company_id, row["document_id"])
            if doc["status"] == "posted":
                self.documents.require_changeable(company_id, doc)
            self.conn.execute(
                "DELETE FROM bank_operations WHERE company_id = ? AND id = ?",
                (
                    company_id,
                    operation_id,
                ),
            )
            self.documents.remove(company_id, doc)
            self._audit(company_id, "bank_operation", operation_id, "delete", {})

    def delete_bank_operations(self, company_id: int, operation_ids: list[int]) -> None:
        """The marked lines of a statement deleted at once: all of them or none — one in
        the closed period keeps them all, and the message names its number."""
        with transaction(self.conn):
            for operation_id in operation_ids:
                self.delete_bank_operation(company_id, operation_id)

    def rebuild_postings(self, company_id: int, since: date | str) -> list[int]:
        """Build the GL documents of posted operations from `since` on (not in the closed
        period) again from the operations (D101); the GL documents that changed."""
        return self.documents.rebuild_each(
            company_id,
            since,
            "bank_operations",
            lambda ids: load_bank_operations(self.conn, company_id, ids),
            lambda op: self._rebuild_bank_operation(company_id, op),
            lambda n, day, error: tr(
                "банковская операция №{n} от {date}: {error}", n=n, date=day, error=error
            ),
        )

    def _rebuild_bank_operation(self, company_id: int, op: BankOperation) -> list[int]:
        postings = self._bank_postings(company_id, op)
        changed = self.documents.rebuild(company_id, op.document_id, op.doc_date, postings, op.memo)
        return [op.document_id] if changed else []

    def move_bank_operations(
        self,
        company_id: int,
        operation_ids: list[int],
        account_id: int,
        subconto: tuple[int | None, ...],
    ) -> None:
        """Operations entered on the wrong bank account go to another one of the same
        currency (D78): each keeps its number and its status, a posted one is posted again.
        A transfer does not go onto the account it transfers to."""
        target = pad_subconto(subconto)
        with transaction(self.conn):
            currency = self._place_currency(company_id, target)
            operations = load_bank_operations(self.conn, company_id, operation_ids)
            for operation_id in operation_ids:
                op = operations.get(operation_id)
                if op is None:
                    raise NotFoundError(tr("документ {id} не найден", id=operation_id))
                if currency != op.currency_id:
                    raise ValidationError(
                        tr(
                            "№{n}: другая валюта счёта — деньги между валютами переводит "
                            "«Конвертация валюты»",
                            n=op.number,
                        )
                    )
                for line in op.lines:
                    if line.account_id == account_id and pad_subconto(line.subconto) == target:
                        raise ValidationError(
                            tr("№{n}: перевод не переносится сам на себя", n=op.number)
                        )
                moved = replace(op, account_id=account_id, subconto=target)
                data = BankOperationInput(
                    **{f.name: getattr(moved, f.name) for f in fields(BankOperationInput)}
                )
                self.save_bank_operation(company_id, data, operation_id, post=op.status == "posted")

    def change_line_account(
        self, company_id: int, operation_ids: list[int], old_id: int, new_id: int
    ) -> int:
        """The lines on one account go to another (a fee loaded before the bank's settings
        said 26): each operation keeps its number and status, a posted one is posted
        again — all of them or none. A subconto of the same kind stays; a fee without one
        gets the item «Комиссия банка». How many operations changed."""
        old, new = self._account(company_id, old_id), self._account(company_id, new_id)
        changed = 0
        with transaction(self.conn):
            operations = load_bank_operations(self.conn, company_id, operation_ids)
            for operation_id in operation_ids:
                op = operations.get(operation_id)
                if op is None:
                    raise NotFoundError(tr("документ {id} не найден", id=operation_id))
                if not any(line.account_id == old_id for line in op.lines):
                    continue
                lines = tuple(
                    replace(
                        line,
                        account_id=new_id,
                        subconto=self._moved_subconto(company_id, op, line.subconto, old, new),
                    )
                    if line.account_id == old_id
                    else line
                    for line in op.lines
                )
                data = BankOperationInput(
                    **{f.name: getattr(op, f.name) for f in fields(BankOperationInput)}
                )
                data = replace(data, lines=lines)
                self.save_bank_operation(company_id, data, operation_id, post=op.status == "posted")
                changed += 1
        return changed

    def _moved_subconto(
        self,
        company_id: int,
        op: BankOperation,
        subconto: Sequence[int | None],
        old: Row,
        new: Row,
    ) -> tuple[int | None, ...]:
        by_kind = {
            kind: value
            for kind, value in zip(account_kinds(old), pad_subconto(subconto), strict=True)
            if kind is not None and value is not None
        }
        moved = fill_subconto(new, by_kind)
        if op.kind == FEE and not any(moved):
            return self.named_subconto(company_id, new["id"], trd("Комиссия банка"))
        return moved

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

    def _first_account_of_type(self, company_id: int, account_type: str) -> int | None:
        """The first active posting account of a type in the chart's order (60.1, 62.1)."""
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE company_id = ? AND account_type = ? "
            "AND is_group = 0 AND active = 1 ORDER BY code IS NULL, code LIMIT 1",
            (company_id, account_type),
        ).fetchone()
        return row["id"] if row else None

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

    def _place_currency(self, company_id: int, subconto: tuple[int | None, ...]) -> int | None:
        """The currency of a bank account: of its element of the directory (D47)."""
        for value_id in subconto:
            if value_id is not None:
                return self._subconto_value(company_id, value_id)["currency_id"]
        return None

    # ---- internals --------------------------------------------------------------------

    def _check_bank_input(self, company_id: int, data: BankOperationInput) -> None:
        """What a draft must already be: real accounts, elements and a known kind."""
        iso_date(data.doc_date)
        if data.direction not in (IN, OUT):
            raise ValidationError(tr("неизвестное направление операции: {d}", d=data.direction))
        if data.kind not in KIND_NAMES:
            raise ValidationError(tr("неизвестный вид операции: {kind}", kind=data.kind))
        if data.account_id is not None:
            self._account(company_id, data.account_id)
        pad_subconto(data.subconto)
        if data.currency_id is not None:
            self._currency(company_id, data.currency_id)
        if data.counterparty_id is not None:
            self._subconto_value(company_id, data.counterparty_id)
        self._require_accounts(company_id, [x.account_id for x in data.lines])
        for line_no, line in enumerate(data.lines, start=1):
            if line.amount < 0:
                raise ValidationError(
                    tr("строка {line}: сумма должна быть больше нуля", line=line_no)
                )
            pad_subconto(line.subconto, line_no)
            try:
                normalize_invoice(line.invoice)
            except ValidationError as e:
                raise ValidationError(tr("строка {line}: {error}", line=line_no, error=e)) from e
            if line.pays_vat and data.direction != OUT:
                raise ValidationError(
                    tr("строка {line}: ƏDV на депозит поставщика — только расход", line=line_no)
                )

    def _require_accounts(self, company_id: int, account_ids: Sequence[int | None]) -> None:
        """Every account of the lines is the company's: one query, not one a line."""
        wanted = {a for a in account_ids if a is not None}
        if not wanted:
            return
        marks = ", ".join("?" * len(wanted))
        known = {
            r["id"]
            for r in self.conn.execute(
                f"SELECT id FROM accounts WHERE company_id = ? AND id IN ({marks})",
                (company_id, *wanted),
            )
        }
        if wanted - known:
            raise NotFoundError(tr("счёт не найден"))

    def _set_checked(self, company_id: int, operation_id: int, checked: bool) -> None:
        self.conn.execute(
            "UPDATE bank_operations SET is_checked = ? WHERE company_id = ? AND id = ?",
            (int(checked), company_id, operation_id),
        )

    def _set_note(self, company_id: int, operation_id: int, note: str) -> None:
        """The import's note on the operation (why a draft, why unidentified, what it
        replaced), shown in the statement next to the line."""
        self.conn.execute(
            "UPDATE bank_operations SET note = ? WHERE company_id = ? AND id = ?",
            (note, company_id, operation_id),
        )

    def _store_bank(self, company_id: int, operation_id: int, data: BankOperationInput) -> None:
        self.conn.execute(
            "UPDATE bank_operations SET direction = ?, kind = ?, account_id = ?, "
            "sc1 = ?, sc2 = ?, sc3 = ?, currency_id = ?, counterparty_id = ?, reference = ? "
            "WHERE company_id = ? AND id = ?",
            (
                data.direction,
                data.kind,
                data.account_id,
                *pad_subconto(data.subconto),
                data.currency_id,
                data.counterparty_id,
                data.reference.strip(),
                company_id,
                operation_id,
            ),
        )
        self.conn.execute(
            "DELETE FROM bank_operation_lines WHERE company_id = ? AND operation_id = ?",
            (company_id, operation_id),
        )
        self.conn.executemany(
            "INSERT INTO bank_operation_lines (company_id, operation_id, line_no, account_id, "
            "sc1, sc2, sc3, amount, invoice, pays_vat) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    company_id,
                    operation_id,
                    line_no,
                    line.account_id,
                    *self._line_subconto(company_id, line, data.counterparty_id),
                    line.amount,
                    normalize_invoice(line.invoice) or "",
                    int(line.pays_vat),
                )
                for line_no, line in enumerate(data.lines, start=1)
            ],
        )

    def _line_subconto(
        self, company_id: int, line: BankLine, counterparty_id: int | None
    ) -> tuple[int | None, int | None, int | None]:
        """The line's subconto with the operation's counterparty in the account's
        counterparty position, when the line leaves it empty."""
        if counterparty_id is None or line.account_id is None:
            return pad_subconto(line.subconto)
        kind_id = self._subconto_value(company_id, counterparty_id)["kind_id"]
        account = self._account(company_id, line.account_id)
        return fill_subconto(account, {kind_id: counterparty_id}, keep=line.subconto)

    def _bank_postings(self, company_id: int, data: BankOperationInput) -> list[PostingInput]:
        if data.account_id is None:
            raise ValidationError(tr("не указан банковский счёт"))
        bank = self._account(company_id, data.account_id)
        if bank["account_type"] == "vat_deposit" and data.kind not in VAT_DEPOSIT_KINDS:
            raise ValidationError(
                tr(
                    "с депозитного счёта ƏDV платится только ƏDV: поставщику, от покупателя, "
                    "в бюджет или перевод между своими счетами"
                )
            )
        lines = [line for line in data.lines if line.account_id is not None or line.amount]
        if not lines:
            raise ValidationError(tr("в операции нет строк"))
        rate = None
        if data.currency_id is not None:
            found = rate_on(self.conn, company_id, data.currency_id, data.doc_date)
            if found is None:
                raise ValidationError(
                    no_rate_text(
                        self._currency(company_id, data.currency_id)["code"], data.doc_date
                    )
                )
            rate = found.per_unit
        bank_sc = pad_subconto(data.subconto)
        postings = []
        for line_no, line in enumerate(lines, start=1):
            if line.account_id is None:
                raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))
            if not line.amount:
                raise ValidationError(tr("строка {line}: нулевая сумма", line=line_no))
            sc = self._line_subconto(company_id, line, data.counterparty_id)
            if line.account_id == data.account_id and sc == bank_sc:
                raise ValidationError(
                    tr("строка {line}: деньги переводятся на тот же счёт", line=line_no)
                )
            value = line.amount if rate is None else to_base(line.amount, rate)
            dt, ct = (
                (line.account_id, data.account_id)
                if data.direction == OUT
                else (
                    data.account_id,
                    line.account_id,
                )
            )
            dt_sc, ct_sc = (sc, bank_sc) if data.direction == OUT else (bank_sc, sc)
            postings.append(
                PostingInput(
                    dt,
                    ct,
                    from_minor(value),
                    dt_sc,
                    ct_sc,
                    data.memo,
                    data.currency_id,
                    None if data.currency_id is None else from_minor(line.amount),
                    line.invoice,
                    pays_vat=line.pays_vat,
                )
            )
        return postings

    def _bank_row(self, company_id: int, operation_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM bank_operations WHERE company_id = ? AND id = ?",
            (company_id, operation_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("документ {id} не найден", id=operation_id))
        return row
