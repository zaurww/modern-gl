"""The bank accounts of the company (D47): a GL account and an element of its bank
account directory; a cash desk (50) is one too — money the same way, without a bank."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.common import pad_subconto
from modern_gl.domain.currency import CURRENCY_ONLY, NO_CURRENCY
from modern_gl.i18n import sort_key
from modern_gl.infrastructure.db import Connection, Row


@dataclass(frozen=True)
class BankPlace:
    """A bank account of the company: a GL account (51) and an element of its bank account
    directory (Kapital Bank AZN), or the GL account alone when it has no directory."""

    account_id: int
    value_id: int | None
    name: str
    account_code: str
    currency_id: int | None  # the element's currency; None: manat (or not fixed)
    currency: str  # its code, "" for manat
    account_type: str | None

    @property
    def is_cash(self) -> bool:
        """A cash desk (50), not a bank account: no bank's statement to check against."""
        return self.account_type == "cash"

    @property
    def key(self) -> tuple[int, int | None]:
        return self.account_id, self.value_id

    @property
    def subconto(self) -> tuple[int | None, int | None, int | None]:
        return pad_subconto(() if self.value_id is None else (self.value_id,))


def bank_places(conn: Connection, company_id: int) -> list[BankPlace]:
    """Bank accounts: each element of the bank account directory under the GL accounts it
    was used on; an element never used is under the first account that fits its currency
    (a USD account under 52, not 51). A GL account without the directory is one place."""
    accounts = _bank_accounts(conn, company_id)
    values = _bank_values(conn, company_id)
    used = _used_pairs(conn, company_id)

    with_directory = [a for a in accounts if a["position"] is not None]
    places: list[BankPlace] = []
    for account in accounts:
        if account["position"] is None:
            places.append(
                BankPlace(
                    account["id"],
                    None,
                    account["name"],
                    account["code"],
                    None,
                    "",
                    account["account_type"],
                )
            )
            continue
        for value in values:
            here = (account["id"], value["id"]) in used
            if not here:
                anywhere = any((a["id"], value["id"]) in used for a in with_directory)
                first = next((a for a in with_directory if _fits(a, value)), None)
                here = not anywhere and first is not None and first["id"] == account["id"]
            if here:
                places.append(
                    BankPlace(
                        account["id"],
                        value["id"],
                        value["name"],
                        account["code"],
                        value["currency_id"],
                        value["currency"] or "",
                        account["account_type"],
                    )
                )
    order = {a["id"]: i for i, a in enumerate(accounts)}
    places.sort(key=lambda p: (order[p.account_id], sort_key(p.name)))
    return places


def transfer_targets(
    conn: Connection, company_id: int, key: tuple[int, int | None], currency_id: int | None
) -> list[BankPlace]:
    """Where money of a bank place (its `key`) can be moved: the other places of its
    currency."""
    return [
        p for p in bank_places(conn, company_id) if p.key != key and p.currency_id == currency_id
    ]


def _bank_accounts(conn: Connection, company_id: int) -> list[Row]:
    """The GL accounts money is in the bank on, with the position of the bank account
    directory among their subconto (None: the account has no such directory); a cash
    desk once money moved on it — a company without cash sees no empty «Касса»."""
    return conn.execute(
        """
        SELECT a.id, COALESCE(a.code, a.name) AS code, a.name, a.currency, a.account_type,
               CASE WHEN k1.code = 'bank_account' THEN 1
                    WHEN k2.code = 'bank_account' THEN 2
                    WHEN k3.code = 'bank_account' THEN 3 END AS position
        FROM accounts a
        LEFT JOIN subconto_kinds k1 ON k1.id = a.sc1_kind_id
        LEFT JOIN subconto_kinds k2 ON k2.id = a.sc2_kind_id
        LEFT JOIN subconto_kinds k3 ON k3.id = a.sc3_kind_id
        WHERE a.company_id = :c AND a.is_group = 0 AND a.active = 1
          AND (a.account_type IN ('bank', 'vat_deposit')
               OR (a.account_type = 'cash' AND (
                   EXISTS (SELECT 1 FROM postings p WHERE p.company_id = :c
                           AND p.debit_account_id = a.id)
                   OR EXISTS (SELECT 1 FROM postings p WHERE p.company_id = :c
                              AND p.credit_account_id = a.id)
                   OR EXISTS (SELECT 1 FROM bank_operations o WHERE o.company_id = :c
                              AND o.account_id = a.id)))
               OR (a.account_type IS NULL AND 'bank_account' IN (k1.code, k2.code, k3.code)))
        ORDER BY a.code IS NULL, a.code, a.name
        """,
        {"c": company_id},
    ).fetchall()


def _bank_values(conn: Connection, company_id: int) -> list[Row]:
    """The elements of the bank account directory with their currency."""
    return conn.execute(
        "SELECT v.id, v.name, v.currency_id, c.code AS currency FROM subconto_values v "
        "JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'bank_account' "
        "LEFT JOIN currencies c ON c.id = v.currency_id "
        "WHERE v.company_id = ? AND v.active = 1 AND v.is_group = 0",
        (company_id,),
    ).fetchall()


def _used_pairs(conn: Connection, company_id: int) -> set[tuple[int, int]]:
    """(GL account, subconto value) pairs postings, bank operations, statements or an
    account's details have used (D78: a card on 55, not under 51)."""
    return {
        (r[0], r[1])
        for r in conn.execute(
            """
            SELECT debit_account_id, value FROM (
                SELECT debit_account_id, dt_sc1 AS value FROM postings WHERE company_id = :c
                UNION SELECT debit_account_id, dt_sc2 FROM postings WHERE company_id = :c
                UNION SELECT debit_account_id, dt_sc3 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc1 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc2 FROM postings WHERE company_id = :c
                UNION SELECT credit_account_id, ct_sc3 FROM postings WHERE company_id = :c
                UNION SELECT account_id, sc1 FROM bank_operations WHERE company_id = :c
                UNION SELECT account_id, sc2 FROM bank_operations WHERE company_id = :c
                UNION SELECT account_id, sc3 FROM bank_operations WHERE company_id = :c
                UNION SELECT account_id, value_id FROM bank_account_details WHERE company_id = :c
                UNION SELECT account_id, value_id FROM bank_statements WHERE company_id = :c
            ) WHERE value IS NOT NULL
            """,
            {"c": company_id},
        )
    }


def _fits(account: Row, value: Row) -> bool:
    if account["currency"] == NO_CURRENCY:
        return value["currency_id"] is None
    if account["currency"] == CURRENCY_ONLY:
        return value["currency_id"] is not None
    return True
