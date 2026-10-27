"""Bank accounts and statements of the module «Банк» (D78): what kind an account is (a card
with its last digits and holder), and the statements — a period and the balance at its
end by the bank. Neither changes a posting: lines are read from postings."""

from __future__ import annotations

from modern_gl.application.bank.accounts import ACCOUNT_KINDS
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.module import ModuleBase
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import insert, transaction

KIND_CODES = {kind for kind, _ in ACCOUNT_KINDS}


class BankStatementCommands(ModuleBase):
    def add_bank_account(
        self,
        company_id: int,
        name: str,
        account: int | str,
        kind: str,
        *,
        currency_id: int | None = None,
        card_digits: str = "",
        holder_id: int | None = None,
        iban: str = "",
    ) -> int:
        """A new bank account or card: an element of the bank account directory under the
        GL account (55 for a card), with its details; returns the element's id."""
        with transaction(self.conn):
            account_id = self._account(company_id, account)["id"]
            directory = self.ledger.subconto_kind_id(company_id, "bank_account")
            value_id = self.ledger.add_subconto_value(company_id, directory, name)
            if currency_id is not None:
                self.ledger.set_subconto_value_currency(company_id, value_id, currency_id)
            self.set_bank_account(
                company_id,
                account_id,
                value_id,
                kind=kind,
                card_digits=card_digits,
                holder_id=holder_id,
                iban=iban,
            )
        return value_id

    def set_bank_account(  # noqa: PLR0913 the bank account form's fields, keyword-only
        self,
        company_id: int,
        account_id: int,
        value_id: int | None,
        *,
        kind: str,
        card_digits: str = "",
        holder_id: int | None = None,
        iban: str = "",
        closed: bool = False,
        name: str | None = None,
    ) -> None:
        """The details of a bank account: its kind (the group of the list), the card's
        last 4 digits and holder, the IBAN, closed; `name` — its element renamed, in the
        same transaction."""
        card_digits, iban = card_digits.strip(), iban.replace(" ", "").upper()
        if kind not in KIND_CODES:
            raise ValidationError(tr("неизвестный вид банковского счёта: {kind}", kind=kind))
        if card_digits and not (len(card_digits) == 4 and card_digits.isdigit()):
            raise ValidationError(tr("последние цифры карты — это 4 цифры"))
        with transaction(self.conn):
            self._account(company_id, account_id)
            if name is not None and value_id is not None:
                current = self._subconto_value(company_id, value_id)["name"]
                if name.strip() != current:
                    self.ledger.update_subconto_value(company_id, value_id, name)
            details = (kind, card_digits, holder_id, iban, int(closed))
            found = self._details_id(company_id, account_id, value_id)
            if found is None:
                insert(
                    self.conn,
                    "INSERT INTO bank_account_details (company_id, account_id, value_id, kind, "
                    "card_digits, holder_id, iban, closed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (company_id, account_id, value_id, *details),
                )
            else:
                self.conn.execute(
                    "UPDATE bank_account_details SET kind = ?, card_digits = ?, holder_id = ?, "
                    "iban = ?, closed = ? WHERE company_id = ? AND id = ?",
                    (*details, company_id, found),
                )
            self._audit(
                company_id,
                "bank_account",
                value_id or account_id,
                "update",
                {"kind": kind, "card_digits": card_digits, "closed": closed},
            )

    def _details_id(self, company_id: int, account_id: int, value_id: int | None) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM bank_account_details WHERE company_id = ? AND account_id = ? "
            "AND COALESCE(value_id, 0) = ?",
            (company_id, account_id, value_id or 0),
        ).fetchone()
        return row["id"] if row else None

    def add_bank_statement(
        self, company_id: int, account_id: int, value_id: int | None, date_from: str, date_to: str
    ) -> int:
        """A statement of the bank account for a day or a period; periods do not overlap."""
        date_from, date_to = iso_date(date_from), iso_date(date_to)
        if date_to < date_from:
            raise ValidationError(tr("конец периода выписки раньше его начала"))
        with transaction(self.conn):
            label = account_label(self._account(company_id, account_id))
            overlap = self.conn.execute(
                "SELECT date_from, date_to FROM bank_statements WHERE company_id = ? "
                "AND account_id = ? AND COALESCE(value_id, 0) = ? "
                "AND date_from <= ? AND date_to >= ?",
                (company_id, account_id, value_id or 0, date_to, date_from),
            ).fetchone()
            if overlap:
                raise ValidationError(
                    tr(
                        "счёт {code}: на эти дни уже есть выписка {start} — {end}",
                        code=label,
                        start=overlap["date_from"],
                        end=overlap["date_to"],
                    )
                )
            statement_id = insert(
                self.conn,
                "INSERT INTO bank_statements (company_id, account_id, value_id, date_from, "
                "date_to) VALUES (?, ?, ?, ?, ?)",
                (company_id, account_id, value_id, date_from, date_to),
            )
            self._audit(
                company_id,
                "bank_statement",
                statement_id,
                "create",
                {"from": date_from, "to": date_to},
            )
        return statement_id

    def set_bank_closing(
        self,
        company_id: int,
        account_id: int,
        value_id: int | None,
        date_from: str,
        date_to: str,
        amount: int | None,
    ) -> int:
        """The balance at the end of the statement by the bank (None: not entered). A day
        nothing was entered for becomes a statement. Returns the statement's id."""
        date_from, date_to = iso_date(date_from), iso_date(date_to)
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT id FROM bank_statements WHERE company_id = ? AND account_id = ? "
                "AND COALESCE(value_id, 0) = ? AND date_from = ? AND date_to = ?",
                (company_id, account_id, value_id or 0, date_from, date_to),
            ).fetchone()
            statement_id = (
                row["id"]
                if row
                else self.add_bank_statement(company_id, account_id, value_id, date_from, date_to)
            )
            self.conn.execute(
                "UPDATE bank_statements SET bank_closing = ? WHERE company_id = ? AND id = ?",
                (amount, company_id, statement_id),
            )
            self._audit(
                company_id, "bank_statement", statement_id, "update", {"bank_closing": amount}
            )
        return statement_id
