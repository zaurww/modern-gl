"""What posting checks: balanced accounts in use, subconto of the right kinds,
currency amounts where the account keeps them."""

from __future__ import annotations

import json
import sqlite3

from modern_gl.application.common import MAX_SUBCONTO
from modern_gl.application.ledger.base import account_label
from modern_gl.application.ledger.inputs import SIDES
from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.application.queries import is_opening_document
from modern_gl.domain.accounts import OPENING_BALANCE
from modern_gl.domain.currency import CURRENCY_OPTIONAL
from modern_gl.domain.errors import PeriodClosedError, ValidationError
from modern_gl.i18n import tr


class PostingChecks(SubcontoCommands):
    def _validate_for_posting(self, company_id: int, doc: sqlite3.Row) -> None:
        self._require_open_period(company_id, doc)
        postings = self.conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (doc["id"],)
        ).fetchall()
        if not postings:
            raise ValidationError(tr("документ №{n} без проводок", n=doc["number"]))
        accounts, values = self._rows_of(company_id, postings)
        self._require_not_opening_account(company_id, doc, accounts)
        is_reversal = doc["reversal_of"] is not None
        currencies = {
            r["id"]: r["code"]
            for r in self.conn.execute(
                "SELECT id, code FROM currencies WHERE company_id = ?", (company_id,)
            )
        }
        # a contract may stay empty: many suppliers have none, only the e-qaimə
        optional = {
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM subconto_kinds WHERE company_id = ? AND owner_kind_id IS NOT NULL",
                (company_id,),
            )
        }
        for p in postings:
            self._validate_currency(p, accounts, values, currencies)
            self._validate_line(p, accounts, values, optional, is_reversal)

    def _require_open_period(self, company_id: int, doc: sqlite3.Row) -> None:
        closed = self._company(company_id)["closed_through"]
        if closed is not None and doc["doc_date"] <= closed:
            raise PeriodClosedError(
                tr(
                    "документ №{number} от {date}: период закрыт по {closed}",
                    number=doc["number"],
                    date=doc["doc_date"],
                    closed=closed,
                )
            )

    def _rows_of(
        self, company_id: int, postings: list[sqlite3.Row]
    ) -> tuple[dict[int, sqlite3.Row], dict[int, sqlite3.Row]]:
        """The accounts and subconto values of the postings (with the owners of contracts)."""
        accounts = self._rows_by_id(
            "accounts",
            company_id,
            {p[f"{side}_account_id"] for p in postings for side, _ in SIDES},
        )
        values = self._rows_by_id(
            "subconto_values",
            company_id,
            {
                p[f"{prefix}_sc{i}"]
                for p in postings
                for _, prefix in SIDES
                for i in range(1, MAX_SUBCONTO + 1)
            }
            - {None},
        )
        owners = {v["owner_id"] for v in values.values()} - {None} - set(values)
        values |= self._rows_by_id("subconto_values", company_id, owners)
        return accounts, values

    def _require_not_opening_account(
        self, company_id: int, doc: sqlite3.Row, accounts: dict[int, sqlite3.Row]
    ) -> None:
        control = self.conn.execute(
            "SELECT account_id FROM account_roles WHERE company_id = ? AND role = ?",
            (company_id, OPENING_BALANCE),
        ).fetchone()
        if (
            control is not None
            and control["account_id"] in accounts
            and not is_opening_document(self.conn, company_id, doc["id"])
        ):
            raise ValidationError(
                tr("счёт ввода начальных остатков проводится только в разделе «Начальные остатки»")
            )

    def _validate_line(
        self,
        p: sqlite3.Row,
        accounts: dict[int, sqlite3.Row],
        values: dict[int, sqlite3.Row],
        optional: set[int],
        is_reversal: bool,
    ) -> None:
        """The sign of the amount, and each side: a leaf account, active, its subconto."""
        line = p["line_no"]
        if is_reversal and p["amount"] >= 0:
            raise ValidationError(
                tr("строка {line}: сумма сторно должна быть отрицательной", line=line)
            )
        if not is_reversal and p["amount"] <= 0:
            raise ValidationError(tr("строка {line}: сумма должна быть положительной", line=line))
        for side, prefix in SIDES:
            acc = accounts[p[f"{side}_account_id"]]
            label = tr(
                "строка {line}, {side} {code}",
                line=line,
                side=tr("Дт" if side == "debit" else "Кт"),
                code=account_label(acc),
            )
            if acc["is_group"]:
                raise ValidationError(tr("{label}: нельзя проводить на группу счетов", label=label))
            if not acc["active"] and not is_reversal:
                raise ValidationError(tr("{label}: счёт не активен", label=label))
            self._validate_subconto(acc, p, prefix, label, values, optional)
            if not is_reversal:
                self._validate_owners(p, prefix, label, values)

    def _rows_by_id(self, table: str, company_id: int, ids: set[int]) -> dict[int, sqlite3.Row]:
        """Rows of a company table (accounts, subconto_values) with these ids, by id."""
        if not ids:
            return {}
        rows = self.conn.execute(
            f"SELECT * FROM {table} "
            "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
            (company_id, json.dumps(sorted(ids))),
        )
        return {r["id"]: r for r in rows}

    @staticmethod
    def _validate_subconto(
        acc: sqlite3.Row,
        p: sqlite3.Row,
        prefix: str,
        label: str,
        values: dict[int, sqlite3.Row],
        optional: set[int],
    ) -> None:
        """Each subconto position of the account is filled with a value of its kind; one
        of an `optional` kind (a contract) may be left empty, and so may a position added
        when the account already had postings (D61)."""
        for i in range(1, MAX_SUBCONTO + 1):
            kind_id = acc[f"sc{i}_kind_id"]
            value_id = p[f"{prefix}_sc{i}"]
            if kind_id is None:
                if value_id is not None:
                    raise ValidationError(tr("{label}: у счёта нет субконто {i}", label=label, i=i))
                continue
            if value_id is None:
                if kind_id in optional or acc["sc_optional"] & (1 << (i - 1)):
                    continue
                raise ValidationError(tr("{label}: не заполнено субконто {i}", label=label, i=i))
            if values[value_id]["kind_id"] != kind_id:
                raise ValidationError(tr("{label}: субконто {i} не того вида", label=label, i=i))
            if values[value_id]["is_group"]:
                raise ValidationError(
                    tr(
                        "{label}: «{name}» — группа, выберите элемент из неё",
                        label=label,
                        name=values[value_id]["name"],
                    )
                )

    @staticmethod
    def _validate_owners(
        p: sqlite3.Row, prefix: str, label: str, values: dict[int, sqlite3.Row]
    ) -> None:
        """A contract of a counterparty goes only next to that counterparty."""
        side = [values[v] for i in range(1, MAX_SUBCONTO + 1) if (v := p[f"{prefix}_sc{i}"])]
        for value in side:
            if value["owner_id"] is None:
                continue
            owner = values[value["owner_id"]]
            other = next(
                (w for w in side if w["kind_id"] == owner["kind_id"] and w["id"] != owner["id"]),
                None,
            )
            if other is not None:
                raise ValidationError(
                    tr(
                        "{label}: «{name}» относится к «{owner}», а не к «{other}»",
                        label=label,
                        name=value["name"],
                        owner=owner["name"],
                        other=other["name"],
                    )
                )

    @staticmethod
    def _validate_currency(
        p: sqlite3.Row,
        accounts: dict[int, sqlite3.Row],
        values: dict[int, sqlite3.Row],
        currencies: dict[int, str],
    ) -> None:
        """A side on a currency account needs the posting's currency, unless the account
        takes manat too (CURRENCY_OPTIONAL) and no element of that side has a currency;
        a posting without currency accounts has no currency. Elements with a currency
        (a USD bank account, a contract in EUR) accept only that currency."""
        line = p["line_no"]
        currency_sides = [
            (side, prefix)
            for side, prefix in SIDES
            if accounts[p[f"{side}_account_id"]]["currency"]
        ]
        if not currency_sides:
            if p["currency_id"] is not None:
                raise ValidationError(
                    tr("строка {line}: валюта указана, но счета без валютного учёта", line=line)
                )
            return
        for side, prefix in currency_sides:
            label = tr(
                "строка {line}, {side} {code}",
                line=line,
                side=tr("Дт" if side == "debit" else "Кт"),
                code=account_label(accounts[p[f"{side}_account_id"]]),
            )
            optional = accounts[p[f"{side}_account_id"]]["currency"] == CURRENCY_OPTIONAL
            for i in range(1, MAX_SUBCONTO + 1):
                value = values.get(p[f"{prefix}_sc{i}"])
                if value is None or value["currency_id"] is None:
                    continue
                if p["currency_id"] is None:
                    raise ValidationError(
                        tr(
                            "{label}: «{name}» в валюте {expected} — укажите сумму в валюте",
                            label=label,
                            name=value["name"],
                            expected=currencies.get(value["currency_id"], "?"),
                        )
                    )
                if value["currency_id"] != p["currency_id"]:
                    raise ValidationError(
                        tr(
                            "{label}: «{name}» в валюте {expected}, а проводка в {actual}",
                            label=label,
                            name=value["name"],
                            expected=currencies.get(value["currency_id"], "?"),
                            actual=currencies[p["currency_id"]],
                        )
                    )
            if p["currency_id"] is None and not optional:
                raise ValidationError(tr("{label}: не указана валюта", label=label))
        if p["currency_id"] is not None and p["currency_amount"] * p["amount"] < 0:
            raise ValidationError(
                tr(
                    "строка {line}: сумма в валюте и сумма в манатах разных знаков",
                    line=line,
                )
            )
