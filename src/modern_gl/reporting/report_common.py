"""What the ledger reports share: the books, the documents a report reads, turnovers and
the rows of the reports, the parameters of a period, the accounts of the chart."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row

COMMON = ("common",)
IFRS = ("common", "ifrs_adj")
TAX = ("common", "tax_adj")

# Posted documents of the requested book up to :date_to.
_DOCS_CTE = """
docs AS (
    SELECT d.id, d.doc_date, d.number, d.memo
    FROM documents d
    JOIN layers l ON l.id = d.layer_id
    WHERE d.company_id = :company_id
      AND d.status = 'posted'
      AND d.doc_date <= :date_to
      AND l.code IN (SELECT value FROM json_each(:layers))
)"""


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
class SubcontoRow(Turnovers):
    value_id: int | None = None
    name: str = ""
    # ОСВ по субконто in levels: 0 = a counterparty, 1 = its contract under it…
    depth: int = 0
    # the values from the first level down to this row: (counterparty, contract)
    path: tuple[int | None, ...] = ()
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


@dataclass
class AccountCard:
    opening: int
    lines: list[CardLine] = field(default_factory=list)
    # currency accounts: net balance (Dt - Ct) in each currency, at start and at end
    currency_opening: dict[str, int] = field(default_factory=dict)
    currency_closing: dict[str, int] = field(default_factory=dict)

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


def _params(conn, company_id, date_from, date_to, layers) -> dict:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    known = {
        r["code"]
        for r in conn.execute("SELECT code FROM layers WHERE company_id = ?", (company_id,))
    }
    unknown = set(layers) - known
    if unknown:
        raise NotFoundError(tr("неизвестные слои: {layers}", layers=sorted(unknown)))
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "layers": json.dumps(list(layers)),
    }


def _accounts(conn: Connection, company_id: int) -> dict[int, Row]:
    return {
        r["id"]: r
        for r in conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? ORDER BY code IS NULL, code, name",
            (company_id,),
        )
    }


def _subtree(accounts: dict[int, Row], root_id: int) -> list[int]:
    children = defaultdict(list)
    for a in accounts.values():
        children[a["parent_id"]].append(a["id"])
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
