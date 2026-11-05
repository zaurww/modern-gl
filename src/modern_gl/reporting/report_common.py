"""What the ledger reports share: turnovers and the rows of the reports, the accounts of
the chart. The books and the documents a report reads — `application/books.py`."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from modern_gl.application.books import docs_cte
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row

_DOCS_CTE = docs_cte("d.id, d.doc_date, d.number, d.memo")


@dataclass
class Turnovers:
    opening_dt: int = 0
    opening_ct: int = 0
    turnover_dt: int = 0
    turnover_ct: int = 0
    closing_dt: int = 0
    closing_ct: int = 0

    def add(self, other: Turnovers) -> None:
        self.opening_dt += other.opening_dt
        self.opening_ct += other.opening_ct
        self.turnover_dt += other.turnover_dt
        self.turnover_ct += other.turnover_ct
        self.closing_dt += other.closing_dt
        self.closing_ct += other.closing_ct

    def is_zero(self) -> bool:
        return not any(
            (
                self.opening_dt,
                self.opening_ct,
                self.turnover_dt,
                self.turnover_ct,
                self.closing_dt,
                self.closing_ct,
            )
        )

    @classmethod
    def from_net(cls, opening: int, dt: int, ct: int) -> Turnovers:
        t = cls(turnover_dt=dt, turnover_ct=ct)
        t.opening_dt, t.opening_ct = _split(opening)
        t.closing_dt, t.closing_ct = _split(opening + dt - ct)
        return t


@dataclass
class OsvRow(Turnovers):
    account_id: int = 0
    code: str = ""
    name: str = ""
    depth: int = 0
    is_group: bool = False
    # a row of «Развернуть по субконто» under its account (D110): the values from the
    # first subconto down to it; () — the account itself
    subconto: tuple[int | None, ...] = ()
    # balance on the side this account should not have (see domain.accounts.wrong_side)
    opening_wrong: bool = False
    closing_wrong: bool = False


@dataclass
class Osv:
    rows: list[OsvRow]
    total: Turnovers
    # account id -> balances split by its first subconto (only accounts that have one)
    subconto: dict[int, list[SubcontoRow]] = field(default_factory=dict)
    # currency account id -> its balances and turnovers in each currency (in that currency)
    currency: dict[int, list[CurrencyRow]] = field(default_factory=dict)

    @property
    def wrong_side(self) -> list[OsvRow]:
        """Accounts whose opening or closing balance sits on the unexpected side."""
        return [r for r in self.rows if r.opening_wrong or r.closing_wrong]


@dataclass
class QuantityMoves:
    """How many on a counted account (D199), in millionths of a unit: at the start,
    in (debit) and out (credit) in the period."""

    opening: int = 0
    incoming: int = 0
    outgoing: int = 0

    @property
    def closing(self) -> int:
        return self.opening + self.incoming - self.outgoing


@dataclass
class SubcontoRow(Turnovers):
    value_id: int | None = None
    name: str = ""
    # ОСВ по субконто in levels: 0 = a counterparty, 1 = its contract under it…
    depth: int = 0
    # the values from the first level down to this row: (counterparty, contract)
    path: tuple[int | None, ...] = ()
    # a row of one e-qaimə under the last level (D110): its number, "" — the lines
    # without one; None — not such a row
    invoice: str | None = None
    # a currency account: net balance (Dt - Ct) at the end in each currency ("USD": …)
    currency_closing: dict[str, int] = field(default_factory=dict)
    # a counted account (01, 12…): how many; None — the account keeps no quantity
    quantity: QuantityMoves | None = None


@dataclass
class SubcontoAnalysisRow(Turnovers):
    """Анализ субконто (D125): an element of a directory (depth 0) and, under it, each
    account that carries the element (depth 1)."""

    value_id: int | None = None  # None — the postings where the position was left empty
    name: str = ""
    depth: int = 0
    account_id: int | None = None  # the account of a depth-1 row
    code: str = ""
    # a currency account: net balance (Dt - Ct) at the end in each currency ("USD": …)
    currency_closing: dict[str, int] = field(default_factory=dict)


@dataclass
class CurrencyRow(Turnovers):
    """Amounts in the currency itself (minor units), not in manat."""

    currency_id: int = 0
    code: str = ""


@dataclass
class CardLine:
    doc_date: str
    number: int
    document_id: int
    memo: str
    corr_code: str  # code of the corresponding account, or its name if it has no code
    debit: int
    credit: int
    balance: int  # running net balance (Dt - Ct) after this line
    corr_id: int = 0
    # on a currency account: the posting's currency and the amount in it on this side
    currency: str = ""
    currency_debit: int = 0
    currency_credit: int = 0
    invoice: str = ""  # e-qaimə number
    invoice_kind: str = ""  # "customs": a customs declaration
    # a counted account (D199): how many came in / went out, and how many after the line
    quantity_debit: int = 0
    quantity_credit: int = 0
    quantity_balance: int = 0


@dataclass
class AccountCard:
    opening: int
    lines: list[CardLine] = field(default_factory=list)
    # a counted account (01, 12…, D199): how many at the start; None — no quantity kept
    quantity_opening: int | None = None
    # currency accounts: net balance (Dt - Ct) in each currency, at start and at end
    currency_opening: dict[str, int] = field(default_factory=dict)
    currency_closing: dict[str, int] = field(default_factory=dict)

    @property
    def closing(self) -> int:
        return self.lines[-1].balance if self.lines else self.opening

    @property
    def quantity_closing(self) -> int | None:
        if self.quantity_opening is None or not self.lines:
            return self.quantity_opening
        return self.lines[-1].quantity_balance


@dataclass
class SubcontoCardLine:
    """A posting carrying one element (D126): on its debit side, its credit side or both."""

    doc_date: str
    number: int
    document_id: int
    memo: str
    debit_code: str  # the debit account's code, or its name without one
    credit_code: str
    debit: int  # the amount, when the element is on the debit side
    credit: int  # … on the credit side (both: the balance does not move)
    balance: int  # running net balance (Dt - Ct) after this line
    debit_id: int = 0
    credit_id: int = 0
    invoice: str = ""
    invoice_kind: str = ""


@dataclass
class SubcontoCard:
    opening: int
    lines: list[SubcontoCardLine] = field(default_factory=list)

    @property
    def closing(self) -> int:
        return self.lines[-1].balance if self.lines else self.opening


@dataclass
class CorrRow:
    corr_code: str  # "" when the account has no code
    corr_name: str
    debit: int  # account debited, corr account credited
    credit: int  # account credited, corr account debited
    corr_id: int = 0


def _split(net: int) -> tuple[int, int]:
    return (net, 0) if net >= 0 else (0, -net)


def _accounts(conn: Connection, company_id: int) -> dict[int, Row]:
    return {
        r["id"]: r
        for r in conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? ORDER BY code IS NULL, code, name",
            (company_id,),
        )
    }


class Adds(Protocol):
    def add(self, other: Any) -> None: ...


def _children(accounts: dict[int, Row]) -> dict[int | None, list[int]]:
    """parent -> its accounts, in the order of `accounts` (by code)."""
    children: dict[int | None, list[int]] = defaultdict(list)
    for a in accounts.values():
        children[a["parent_id"]].append(a["id"])
    return children


def fold_chart[R: Adds](
    accounts: dict[int, Row], make: Callable[[Row, int], R], keep: Callable[[R], bool]
) -> tuple[list[R], list[R]]:
    """The rows of a report in the order of the chart, a group adding up its children:
    `make` — an account's row at a depth with its own figures; `keep` false drops the
    row with its subtree. Returns the rows kept and the top rows (all, for a total)."""
    children = _children(accounts)
    rows: list[R] = []

    def visit(account_id: int, depth: int) -> R:
        row = make(accounts[account_id], depth)
        position = len(rows)
        rows.append(row)
        for child in children[account_id]:
            row.add(visit(child, depth + 1))
        if not keep(row):
            del rows[position:]  # a silent account and its silent subtree
        return row

    return rows, [visit(top, 0) for top in children[None]]


def _subtree(accounts: dict[int, Row], root_id: int) -> list[int]:
    children = _children(accounts)
    result, stack = [], [root_id]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(children[current])
    return result


def _find_account(accounts: dict[int, Row], account: int | str) -> Row:
    """An account by id (int) or by code (str)."""
    if isinstance(account, int) and account in accounts:
        return accounts[account]
    for a in accounts.values():
        if a["code"] == account:
            return a
    raise NotFoundError(tr("счёт {code} не найден", code=account))
