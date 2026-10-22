"""The statement of one bank account, read from postings: every document that moved it,
with the running balance (D47)."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.bank.operations import IN, OUT
from modern_gl.application.bank.places import BankPlace
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection, Row


@dataclass
class StatementLine:
    document_id: int
    number: int
    doc_date: str
    memo: str
    status: str  # a draft bank operation is listed, but it does not move the balance
    money_in: int
    money_out: int
    balance: int | None  # after this line; None for a draft
    counterparty: str  # names on the other side, «, »-separated
    corr: str  # codes of the other side's accounts
    kind: str = ""  # a bank operation's kind, "conversion", or "" (journal, warehouse…)
    direction: str = ""  # of a bank operation


@dataclass
class Statement:
    opening: int
    lines: list[StatementLine] = field(default_factory=list)
    currency: str = ""  # "" manat

    @property
    def closing(self) -> int:
        posted = [line.balance for line in self.lines if line.balance is not None]
        return posted[-1] if posted else self.opening

    @property
    def total_in(self) -> int:
        return sum(line.money_in for line in self.lines if line.status == "posted")

    @property
    def total_out(self) -> int:
        return sum(line.money_out for line in self.lines if line.status == "posted")


def statement(
    conn: Connection,
    company_id: int,
    place: BankPlace,
    date_from: str,
    date_to: str,
) -> Statement:
    """Every document that moved the bank account in the period (one row per document),
    with the running balance, in the account's currency; draft bank operations too."""
    params = {
        "c": company_id,
        "a": place.account_id,
        "v": place.value_id,
        "from": iso_date(date_from),
        "to": iso_date(date_to),
    }
    rows = _statement_rows(conn, place, params)
    result = Statement(opening=0, currency=place.currency)
    balance = 0
    for r in rows:
        balance += r["money_in"] - r["money_out"]
        if r["doc_date"] < params["from"]:
            result.opening = balance
            continue
        kind = r["kind"] or ("conversion" if r["conversion"] else "")
        result.lines.append(
            StatementLine(
                r["id"],
                r["number"],
                r["doc_date"],
                r["memo"],
                "posted",
                r["money_in"],
                r["money_out"],
                balance,
                r["counterparty"] or "",
                r["corr"] or "",
                kind,
                r["direction"] or "",
            )
        )
    for d in _drafts(conn, place, params):
        result.lines.append(d)
    result.lines.sort(key=lambda line: (line.doc_date, line.number))
    return result


def _statement_rows(conn: Connection, place: BankPlace, params: dict) -> list[Row]:
    """One row per posted document that moved the bank account: money in and out, the
    counterparties and corr accounts, what kind of operation made it."""
    amount = "COALESCE(p.currency_amount, 0)" if place.currency_id is not None else "p.amount"
    sides = []
    for own, other, sign in (("dt", "ct", 1), ("ct", "dt", -1)):
        own_col = "debit_account_id" if own == "dt" else "credit_account_id"
        other_col = "credit_account_id" if own == "dt" else "debit_account_id"
        sides.append(
            f"""
            SELECT p.document_id, {sign} * {amount} AS net, p.{other_col} AS corr_id,
                   p.{other}_sc1 AS o1, p.{other}_sc2 AS o2, p.{other}_sc3 AS o3
            FROM postings p
            WHERE p.company_id = :c AND p.{own_col} = :a
              AND (:v IS NULL OR :v IN (p.{own}_sc1, p.{own}_sc2, p.{own}_sc3))
            """
        )
    moves = " UNION ALL ".join(sides)
    return conn.execute(
        f"""
        WITH moves AS ({moves}),
        docs AS (
            SELECT d.id, d.number, d.doc_date, d.memo,
                   SUM(CASE WHEN m.net > 0 THEN m.net ELSE 0 END) AS money_in,
                   SUM(CASE WHEN m.net < 0 THEN -m.net ELSE 0 END) AS money_out
            FROM moves m
            JOIN documents d ON d.id = m.document_id AND d.status = 'posted'
            JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
            WHERE d.doc_date <= :to
            GROUP BY d.id
        )
        SELECT docs.*,
               (SELECT string_agg(name, ', ') FROM (
                    SELECT DISTINCT v.name FROM moves m
                    JOIN subconto_values v ON v.id IN (m.o1, m.o2, m.o3)
                    JOIN subconto_kinds k ON k.id = v.kind_id
                     AND k.code IN ('counterparty', 'employee', 'bank_account')
                    WHERE m.document_id = docs.id)) AS counterparty,
               (SELECT string_agg(code, ', ') FROM (
                    SELECT DISTINCT COALESCE(a.code, a.name) AS code FROM moves m
                    JOIN accounts a ON a.id = m.corr_id
                    WHERE m.document_id = docs.id)) AS corr,
               o.kind, o.direction,
               (SELECT 1 FROM currency_conversions x
                WHERE x.document_id = docs.id OR x.credit_document_id = docs.id) AS conversion
        FROM docs
        LEFT JOIN bank_operations o ON o.document_id = docs.id
        ORDER BY docs.doc_date, docs.number
        """,
        params,
    ).fetchall()


def _drafts(conn: Connection, place: BankPlace, params: dict) -> list[StatementLine]:
    rows = conn.execute(
        """
        SELECT d.id, d.number, d.doc_date, d.memo, o.kind, o.direction,
               COALESCE(SUM(x.amount), 0) AS total, v.name AS counterparty,
               (SELECT string_agg(code, ', ') FROM (
                    SELECT DISTINCT COALESCE(a.code, a.name) AS code
                    FROM bank_operation_lines y JOIN accounts a ON a.id = y.account_id
                    WHERE y.operation_id = o.id)) AS corr
        FROM bank_operations o
        JOIN documents d ON d.id = o.document_id AND d.status = 'draft'
        LEFT JOIN bank_operation_lines x ON x.operation_id = o.id
        LEFT JOIN subconto_values v ON v.id = o.counterparty_id
        WHERE o.company_id = :c AND o.account_id = :a
          AND (:v IS NULL OR :v IN (o.sc1, o.sc2, o.sc3))
          AND d.doc_date BETWEEN :from AND :to
        GROUP BY o.id
        """,
        params,
    ).fetchall()
    return [
        StatementLine(
            r["id"],
            r["number"],
            r["doc_date"],
            r["memo"],
            "draft",
            r["total"] if r["direction"] == IN else 0,
            r["total"] if r["direction"] == OUT else 0,
            None,
            r["counterparty"] or "",
            r["corr"] or "",
            r["kind"],
            r["direction"],
        )
        for r in rows
    ]


def place_balance(conn: Connection, company_id: int, place: BankPlace, day: str) -> int:
    """The balance of a bank account at the end of the day, in its currency."""
    amount = "COALESCE(p.currency_amount, 0)" if place.currency_id is not None else "p.amount"
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(CASE
            WHEN p.debit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.dt_sc1, p.dt_sc2, p.dt_sc3)) THEN {amount}
            ELSE 0 END), 0)
             - COALESCE(SUM(CASE
            WHEN p.credit_account_id = :a
                 AND (:v IS NULL OR :v IN (p.ct_sc1, p.ct_sc2, p.ct_sc3)) THEN {amount}
            ELSE 0 END), 0)
        FROM postings p
        JOIN documents d ON d.id = p.document_id AND d.status = 'posted'
        JOIN layers l ON l.id = d.layer_id AND l.code = 'common'
        WHERE p.company_id = :c AND d.doc_date <= :day
          AND (p.debit_account_id = :a OR p.credit_account_id = :a)
        """,
        {"c": company_id, "a": place.account_id, "v": place.value_id, "day": iso_date(day)},
    ).fetchone()
    return row[0]
