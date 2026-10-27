"""One payment spread over what it pays (D78): each e-qaimə named, oldest first; then the
counterparty's debt without a number; what is left is an advance — on the advance
account (60.2 / 62.2, role advance_paid / advance_received) or, without one, on the
settlement account itself without an e-qaimə."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modern_gl.application.bank.balance import account_balance
from modern_gl.application.bank.operations import IN, OUT, BankLine, allocate
from modern_gl.application.common import fill_subconto, pad_subconto
from modern_gl.infrastructure.db import Connection

# a settlement account the payment pays off (60.1 when paying out, 62.1 when money comes in)
SETTLES = {"payable": OUT, "receivable": IN}


def counterparty_balance(
    conn: Connection, company_id: int, account_id: int, counterparty_id: int, day: str
) -> int:
    """Dt − Kt of the counterparty on the account at the end of the day (posted, the
    common book): below zero, the company owes it."""
    return account_balance(conn, company_id, account_id, counterparty_id, day)


def payment_lines(  # noqa: PLR0913 one payment's facts, keyword-only
    conn: Connection,
    company_id: int,
    *,
    account_id: int,
    account_type: str | None,
    subconto: Sequence[int | None],
    counterparty_id: int | None,
    amount: int,
    direction: str,
    day: str,
    invoices: Sequence[tuple[str, int | None]] = (),
    advance_account: int | None = None,
) -> list[BankLine]:
    """The lines of one payment. `invoices`: (number, what it still owes; None — not
    known, it takes the whole amount). Only a payment that settles (out on 60, in on 62)
    is spread; any other line is the amount as typed, on its one e-qaimə if any. The
    advance line takes the line's subconto in their places on the advance account — the
    contract, an order (D124) — by kind; the counterparty is put in by the operation."""
    sc = tuple(pad_subconto(subconto))
    if SETTLES.get(account_type or "") != direction or counterparty_id is None:  # not settling
        number = invoices[0][0] if len(invoices) == 1 else ""
        return [BankLine(account_id, amount, sc, number)]
    owed = [amount if still is None else still for _, still in invoices]
    paid, left = allocate(amount, owed)
    lines = [
        BankLine(account_id, part, sc, number)
        for (number, _), part in zip(invoices, paid, strict=True)
        if part
    ]
    if not left:
        return lines
    balance = counterparty_balance(conn, company_id, account_id, counterparty_id, day)
    debt = (-balance if direction == OUT else balance) - sum(paid)
    cover = max(0, min(left, debt))
    if advance_account is None:  # an advance stays on the account: one line for the rest
        return [*lines, BankLine(account_id, left, sc)]
    if cover:
        lines.append(BankLine(account_id, cover, sc))
    if left - cover:
        advance_sc = carried_over(conn, company_id, sc, advance_account)
        lines.append(BankLine(advance_account, left - cover, advance_sc))
    return lines


def carried_over(
    conn: Connection, company_id: int, subconto: Sequence[int | None], account_id: int
) -> tuple[int | None, int | None, int | None]:
    """The values of `subconto` in their places on another account, by their directory:
    a contract and an order typed on 62.1 go with the advance to 62.2."""
    kinds = {
        r["id"]: r["kind_id"]
        for r in conn.execute(
            "SELECT id, kind_id FROM subconto_values WHERE company_id = ? AND id IN (?, ?, ?)",
            (company_id, *pad_subconto(subconto)),
        )
    }
    by_kind = {kinds[v]: v for v in subconto if v is not None and v in kinds}
    account = conn.execute(
        "SELECT sc1_kind_id, sc2_kind_id, sc3_kind_id FROM accounts "
        "WHERE company_id = ? AND id = ?",
        (company_id, account_id),
    ).fetchone()
    return fill_subconto(account, by_kind)


@dataclass(frozen=True)
class AdvanceOffset:
    """One side of «Зачесть авансы» (D78): the advance on its account against the
    unpaid e-qaimə on the settlement account, oldest first."""

    settlement: int  # 60.1 / 62.1
    advance: int  # 60.2 / 62.2
    advance_amount: int
    parts: tuple[tuple[str, int], ...]  # (e-qaimə, amount)
