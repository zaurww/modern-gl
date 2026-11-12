"""The accountable persons (D-new-advance-reports): the account money given to employees
is kept on (71), who owes what on it, and what moved for one of them — issued from the
cash desk or the bank, spent by an advance report, returned. Read from the postings, so
an issue entered in the journal counts as one from the cash desk."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.document_kinds import KIND_SQL, NAME_JOINS, NUMBER_SQL
from modern_gl.domain.accounts import ACCOUNTABLE
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection, Row

EVER = "1900-01-01"


@dataclass(frozen=True)
class AccountableAccount:
    """The account of the accountable persons and where its employee stands (1..3)."""

    id: int
    code: str
    position: int  # the subconto position of the employee directory
    kind_id: int  # the employee directory


@dataclass(frozen=True)
class Person:
    employee_id: int
    name: str
    balance: int  # Dt − Kt: above zero the employee owes, below — the company owes him
    last_day: str  # the last day anything moved for him


@dataclass(frozen=True)
class PersonLine:
    document_id: int
    doc_date: str
    kind: str  # `document_kinds`: «cash_out», «advance_report», «journal»…
    number: int
    memo: str
    issued: int  # Dt 71: given to the employee
    settled: int  # Kt 71: spent by a report or returned
    balance: int  # after the line


@dataclass
class PersonStatement:
    opening: int
    lines: list[PersonLine] = field(default_factory=list[PersonLine])

    @property
    def closing(self) -> int:
        return self.lines[-1].balance if self.lines else self.opening


def accountable_account(conn: Connection, company_id: int) -> AccountableAccount | None:
    """The account of the role «accountable»; without one, the first active account with
    the employee directory of the type «other receivable» or of no type (71, not 70)."""
    rows = conn.execute(
        """
        SELECT a.id, COALESCE(a.code, a.name) AS code, a.sc1_kind_id, a.sc2_kind_id,
               a.sc3_kind_id, k1.code AS c1, k2.code AS c2, k3.code AS c3,
               (r.account_id IS NOT NULL) AS chosen
        FROM accounts a
        LEFT JOIN subconto_kinds k1 ON k1.id = a.sc1_kind_id
        LEFT JOIN subconto_kinds k2 ON k2.id = a.sc2_kind_id
        LEFT JOIN subconto_kinds k3 ON k3.id = a.sc3_kind_id
        LEFT JOIN account_roles r
               ON r.company_id = a.company_id AND r.account_id = a.id AND r.role = :role
        WHERE a.company_id = :c AND a.is_group = 0 AND a.active = 1
          AND (r.account_id IS NOT NULL OR (
               COALESCE(a.account_type, 'other_receivable') = 'other_receivable'
               AND 'employee' IN (k1.code, k2.code, k3.code)))
        ORDER BY chosen DESC, a.code IS NULL, a.code
        """,
        {"c": company_id, "role": ACCOUNTABLE},
    ).fetchall()
    for row in rows:
        found = _employee_position(row)
        if found is not None:
            return AccountableAccount(row["id"], row["code"], *found)
    return None


def _employee_position(row: Row) -> tuple[int, int] | None:
    for position, code in enumerate((row["c1"], row["c2"], row["c3"]), start=1):
        if code == "employee":
            return position, row[f"sc{position}_kind_id"]
    return None


def accountable_people(
    conn: Connection, company_id: int, account: AccountableAccount, day: str
) -> list[Person]:
    """Everyone money moved for on the account up to the day, with what is left: those
    who owe or are owed first, then by name."""
    sc = f"sc{account.position}"
    rows = conn.execute(
        f"""
        WITH moves AS (
            SELECT p.dt_{sc} AS employee_id, p.amount AS net, d.doc_date
            FROM postings p
            JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
            JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
            WHERE p.company_id = :c AND p.debit_account_id = :a AND d.doc_date <= :day
            UNION ALL
            SELECT p.ct_{sc}, -p.amount, d.doc_date
            FROM postings p
            JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
            JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
            WHERE p.company_id = :c AND p.credit_account_id = :a AND d.doc_date <= :day
        )
        SELECT m.employee_id, v.name, SUM(m.net) AS balance, MAX(m.doc_date) AS last_day
        FROM moves m JOIN subconto_values v ON v.id = m.employee_id
        GROUP BY m.employee_id, v.name
        """,
        {"c": company_id, "a": account.id, "day": iso_date(day)},
    ).fetchall()
    people = [Person(r["employee_id"], r["name"], r["balance"], r["last_day"]) for r in rows]
    people.sort(key=lambda p: (p.balance == 0, p.name.casefold()))
    return people


def employee_balance(
    conn: Connection,
    company_id: int,
    account: AccountableAccount,
    employee_id: int,
    day: str,
    *,
    without: int | None = None,
) -> int:
    """What the employee owes at the end of the day (Dt − Kt), leaving out one GL document
    (`without`: the report being written — what he had before it)."""
    sc = f"sc{account.position}"
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE WHEN p.debit_account_id = :a AND p.dt_{sc} = :e
                                 THEN p.amount ELSE 0 END), 0)
             - COALESCE(SUM(CASE WHEN p.credit_account_id = :a AND p.ct_{sc} = :e
                                 THEN p.amount ELSE 0 END), 0)
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        WHERE p.company_id = :c AND d.doc_date <= :day AND d.id <> :w
          AND (p.debit_account_id = :a OR p.credit_account_id = :a)
        """,
        {
            "c": company_id,
            "a": account.id,
            "e": employee_id,
            "day": iso_date(day),
            "w": without or 0,
        },
    ).fetchone()
    return row[0]


def person_statement(
    conn: Connection,
    company_id: int,
    account: AccountableAccount,
    employee_id: int,
    date_from: str,
    date_to: str,
) -> PersonStatement:
    """What moved for the employee in the period, a line per document, with the balance."""
    sc = f"sc{account.position}"
    rows = conn.execute(
        f"""
        WITH moves AS (
            SELECT p.document_id,
                   CASE WHEN p.debit_account_id = :a AND p.dt_{sc} = :e
                        THEN p.amount ELSE 0 END AS issued,
                   CASE WHEN p.credit_account_id = :a AND p.ct_{sc} = :e
                        THEN p.amount ELSE 0 END AS settled
            FROM postings p
            WHERE p.company_id = :c AND (p.debit_account_id = :a OR p.credit_account_id = :a)
        )
        SELECT d.id, d.doc_date, d.memo, {KIND_SQL} AS kind, {NUMBER_SQL} AS number,
               SUM(m.issued) AS issued, SUM(m.settled) AS settled
        FROM moves m
        JOIN documents d ON d.id = m.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        {NAME_JOINS}
        WHERE d.doc_date <= :to
        GROUP BY d.id, d.doc_date, d.memo, own.owner_kind, own.owner_number, ob.document_id,
                 d.number
        HAVING SUM(m.issued) <> 0 OR SUM(m.settled) <> 0
        ORDER BY d.doc_date, d.number
        """,
        {"c": company_id, "a": account.id, "e": employee_id, "to": iso_date(date_to)},
    ).fetchall()
    result = PersonStatement(opening=0)
    balance = 0
    for r in rows:
        balance += r["issued"] - r["settled"]
        if r["doc_date"] < iso_date(date_from):
            result.opening = balance
            continue
        result.lines.append(
            PersonLine(
                r["id"],
                r["doc_date"],
                r["kind"],
                r["number"],
                r["memo"],
                r["issued"],
                r["settled"],
                balance,
            )
        )
    return result
