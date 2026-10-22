"""The statements of one bank account (D78): a day, or a period (a weekend, a card's
month), with the balance at its start and end and what the bank's own statement says.
Lines are read from postings; a statement row keeps only the period and the bank's
balance, so a day money moved on is a statement even before anything is entered for it."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import accumulate

from modern_gl.application.bank.places import BankPlace, bank_places
from modern_gl.application.bank.statement import StatementLine, statement
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.overview import Attention, attention_source

OPEN, OK, DIFF = "open", "ok", "diff"  # not checked against the bank; agrees; does not
EVER = ("1900-01-01", "9999-12-31")


@dataclass(frozen=True)
class BankStatement:
    id: int | None  # None: a day money moved on, nothing entered for it yet
    date_from: str
    date_to: str
    opening: int
    money_in: int
    money_out: int
    lines: int  # posted documents
    drafts: int  # draft bank operations: listed, they do not move the balance
    bank_closing: int | None  # the balance at the end by the bank, None: not entered

    @property
    def closing(self) -> int:
        return self.opening + self.money_in - self.money_out

    @property
    def difference(self) -> int | None:
        """The bank's balance less the program's: below zero, money left the bank that
        is not entered (a fee?)."""
        return None if self.bank_closing is None else self.bank_closing - self.closing

    @property
    def status(self) -> str:
        if self.bank_closing is None:
            return OPEN
        return OK if self.difference == 0 else DIFF


def bank_statements(conn: Connection, company_id: int, place: BankPlace) -> list[BankStatement]:
    """Every statement of the bank account, oldest first: those entered (a period, the
    bank's balance) and each other day money moved on."""
    lines = statement(conn, company_id, place, *EVER).lines
    posted = [line for line in lines if line.status == "posted"]
    days = [line.doc_date for line in posted]
    net = list(accumulate((line.money_in - line.money_out for line in posted), initial=0))
    periods = _entered(conn, company_id, place)
    covered = [(p[1], p[2]) for p in periods]
    for day in sorted({line.doc_date for line in lines}):
        if not any(start <= day <= end for start, end in covered):
            periods.append((None, day, day, None))
    periods.sort(key=lambda p: p[1])
    result = []
    for statement_id, start, end, bank_closing in periods:
        first, last = bisect_left(days, start), bisect_right(days, end)
        inside = posted[first:last]
        result.append(
            BankStatement(
                statement_id,
                start,
                end,
                net[first],
                sum(line.money_in for line in inside),
                sum(line.money_out for line in inside),
                len(inside),
                _drafts_in(lines, start, end),
                bank_closing,
            )
        )
    return result


def _entered(
    conn: Connection, company_id: int, place: BankPlace
) -> list[tuple[int | None, str, str, int | None]]:
    return [
        (r["id"], r["date_from"], r["date_to"], r["bank_closing"])
        for r in conn.execute(
            "SELECT id, date_from, date_to, bank_closing FROM bank_statements "
            "WHERE company_id = ? AND account_id = ? AND COALESCE(value_id, 0) = ? "
            "ORDER BY date_from",
            (company_id, place.account_id, place.value_id or 0),
        )
    ]


def _drafts_in(lines: list[StatementLine], start: str, end: str) -> int:
    return sum(1 for line in lines if line.status == "draft" and start <= line.doc_date <= end)


@attention_source
def bank_attention(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """«Bu gün» (D86): statements whose balance is not the bank's, and bank operations
    left as drafts — up to the day."""
    differ = drafts = 0
    for place in bank_places(conn, company_id):
        for st in bank_statements(conn, company_id, place):
            if st.date_from <= day:
                differ += st.status == DIFF
                drafts += st.drafts
    return [
        Attention(tr("Выписки не сходятся с банком"), differ, ("bank",)),
        Attention(tr("Черновики в банке"), drafts, ("bank",)),
    ]
