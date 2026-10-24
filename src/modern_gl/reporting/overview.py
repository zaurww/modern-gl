"""«Bu gün» (D86): what waits for the accountant, the money on hand and today's rates —
read only, one company, on a day.

The core knows its own rows (journal drafts, cash and bank balances, rates); a module adds
the rows of what waits in it with `attention_source` (D71): the core never asks a module.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from modern_gl.application.books import COMMON
from modern_gl.application.currencies import Rate, latest_rates, list_currencies, rate_on
from modern_gl.application.queries import journal_drafts
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.report_common import _DOCS_CTE

POST_DRAFTS = "post_drafts"  # the row's button: post them all


@dataclass(frozen=True)
class Attention:
    """One thing that waits: «Черновики в журнале · 3» → its place in the sidebar."""

    text: str
    count: int
    place: tuple[str, ...]
    amount: int | None = None  # in kopecks, when a sum tells more than the count
    action: str = ""  # POST_DRAFTS: a button on the row


AttentionSource = Callable[[Connection, int, str], list[Attention]]
_SOURCES: list[AttentionSource] = []


def attention_source(source: AttentionSource) -> AttentionSource:
    """A module's rows of «Требует внимания»: (conn, company_id, ISO day) → rows."""
    if source not in _SOURCES:
        _SOURCES.append(source)
    return source


def attention(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """What waits on the day: the journal's drafts, then each module's rows; only rows
    with something in them."""
    day = iso_date(day)
    rows = [_journal_drafts(conn, company_id, day)]
    for source in _SOURCES:
        rows += source(conn, company_id, day)
    return [r for r in rows if r.count]


def _journal_drafts(conn: Connection, company_id: int, day: str) -> Attention:
    count = len(journal_drafts(conn, company_id, day))
    return Attention(tr("Черновики в журнале"), count, ("journal",), action=POST_DRAFTS)


# ---- money -----------------------------------------------------------------------------

MONEY_TYPES = ("cash", "bank")  # free money: the ƏDV deposit pays only ƏDV (D41)


@dataclass(frozen=True)
class Money:
    """A cash desk or a bank account: its balance in manat, and in its currency."""

    account_id: int
    value_id: int | None
    name: str  # the bank account (Kapital Bank AZN), or the GL account (Касса)
    account_code: str
    balance: int  # kopecks
    currency: str = ""  # "" manat
    currency_balance: int | None = None  # cents of the currency


def money(conn: Connection, company_id: int, day: str) -> list[Money]:
    """Balances of the cash and bank accounts on the day (posted, the common book), by
    the bank account they are kept on; accounts that never moved are left out."""
    params = {
        "company_id": company_id,
        "date_to": iso_date(day),
        "layers": json.dumps(COMMON),
        "types": json.dumps(MONEY_TYPES),
    }
    rows = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc, p.amount AS amount,
                   p.currency_id, p.currency_amount AS currency_amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
            UNION ALL
            SELECT p.credit_account_id, p.ct_sc1, -p.amount, p.currency_id, -p.currency_amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
        )
        SELECT a.id AS account_id, a.code, a.name AS account_name, m.sc, v.name AS value_name,
               SUM(m.amount) AS balance, MIN(c.code) AS currency, MAX(c.code) AS other,
               SUM(COALESCE(m.currency_amount, 0)) AS currency_balance
        FROM moves m
        JOIN accounts a ON a.id = m.account_id AND a.company_id = :company_id
        LEFT JOIN subconto_values v ON v.id = m.sc AND v.company_id = :company_id
        LEFT JOIN currencies c ON c.id = m.currency_id AND c.company_id = :company_id
        WHERE a.account_type IN (SELECT value FROM json_each(:types))
        GROUP BY a.id, a.code, a.name, m.sc, v.name
        """,
        params,
    ).fetchall()
    result = []
    for r in rows:
        # one currency on the account: its own balance too; none or several: manat only
        one = r["currency"] if r["currency"] and r["currency"] == r["other"] else ""
        result.append(
            Money(
                r["account_id"],
                r["sc"],
                r["value_name"] or r["account_name"],
                r["code"] or "",
                r["balance"],
                one,
                r["currency_balance"] if one else None,
            )
        )
    result.sort(key=lambda m: (m.account_code, sort_key(m.name)))
    return result


# ---- rates -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DayRate:
    code: str
    currency_id: int
    rate: Rate | None  # in force on the day (set on it or before)
    day: str

    @property
    def of_the_day(self) -> bool:
        """The rate was set for this very day: nothing to load."""
        return self.rate is not None and self.rate.rate_date == self.day


MAIN_CURRENCIES = ("USD", "EUR")  # first: what an Azerbaijani firm pays in most


def rates(conn: Connection, company_id: int, day: str) -> list[DayRate]:
    """The rate of each active currency on the day: USD and EUR first, then those that
    have a rate at all."""
    day = iso_date(day)
    has_rate = latest_rates(conn, company_id)
    result = [
        DayRate(c.code, c.id, rate_on(conn, company_id, c.id, day), day)
        for c in list_currencies(conn, company_id)
        if c.active and (c.code in MAIN_CURRENCIES or c.id in has_rate)
    ]
    order = {code: i for i, code in enumerate(MAIN_CURRENCIES)}
    result.sort(key=lambda r: (order.get(r.code, len(order)), r.code))
    return result
