"""The statement of one bank account, read from postings: every document that moved it,
with the running balance (D47)."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.bank.balance import account_balance
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
    # a person saw it: False — a bank operation the import posted and no one checked yet
    checked: bool = True


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
                bool(r["checked"]),
            )
        )
    result.lines += _drafts(conn, place, params) + _conversion_drafts(conn, place, params)
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
               o.kind, o.direction, COALESCE(o.is_checked, 1) AS checked,
               EXISTS (SELECT 1 FROM document_owners x
                       WHERE x.company_id = :c AND x.document_id = docs.id
                         AND x.module = 'conversion') AS conversion
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


def _conversion_drafts(conn: Connection, place: BankPlace, params: dict) -> list[StatementLine]:
    """Draft conversions (D37) with a side on the bank account: the debit side on the
    conversion's day, the credit side on its own day when the bank credits later; a fee
    taken from the account goes with the side. Listed as drafts: no balance yet."""
    other = "(SELECT COALESCE(a.code, a.name) FROM accounts a WHERE a.id = {o}_account_id)"
    bank = (
        "(SELECT v.name FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id "
        "AND k.code = 'bank_account' WHERE v.id IN ({o}_sc1, {o}_sc2, {o}_sc3))"
    )
    fees = (
        "(SELECT COALESCE(SUM(f.amount), 0) FROM conversion_fees f "
        "WHERE f.conversion_id = c.id AND f.account_id = :a "
        "AND (:v IS NULL OR :v IN (f.sc1, f.sc2, f.sc3)))"
    )
    sides = []
    for own, o, direction, day in (
        ("from", "to", OUT, "d.doc_date"),
        ("to", "from", IN, "COALESCE(c.to_date, d.doc_date)"),
    ):
        sides.append(
            f"""
            SELECT d.id, d.number, {day} AS doc_date, d.memo, '{direction}' AS direction,
                   COALESCE(c.{own}_amount, 0) AS amount, {fees} AS fees,
                   {bank.format(o=o)} AS counterparty, {other.format(o=o)} AS corr
            FROM currency_conversions c
            JOIN documents d ON d.id = c.document_id AND d.status = 'draft'
            WHERE c.company_id = :c AND c.{own}_account_id = :a
              AND (:v IS NULL OR :v IN (c.{own}_sc1, c.{own}_sc2, c.{own}_sc3))
            """
        )
    rows = conn.execute(
        f"SELECT * FROM ({' UNION ALL '.join(sides)}) WHERE doc_date BETWEEN :from AND :to",
        params,
    ).fetchall()
    return [
        StatementLine(
            r["id"],
            r["number"],
            r["doc_date"],
            r["memo"],
            "draft",
            r["amount"] if r["direction"] == IN else 0,
            (r["amount"] if r["direction"] == OUT else 0) + r["fees"],
            None,
            r["counterparty"] or "",
            r["corr"] or "",
            "conversion",
            r["direction"],
        )
        for r in rows
    ]


def place_balance(conn: Connection, company_id: int, place: BankPlace, day: str) -> int:
    """The balance of a bank account at the end of the day, in its currency."""
    return account_balance(
        conn,
        company_id,
        place.account_id,
        place.value_id,
        day,
        in_currency=place.currency_id is not None,
    )
