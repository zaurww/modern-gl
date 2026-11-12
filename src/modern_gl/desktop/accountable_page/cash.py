"""Money for an accountable person goes through «Банк и касса»: the form of a cash
operation opens filled in — to the employee from the cash desk (an issue, an overspend
paid back) or from him into it (what is left returned). Dt 71 [employee] / Kt 50, or
Dt 50 / Kt 71 [employee]."""

from __future__ import annotations

from modern_gl.application.accountable import AccountableAccount
from modern_gl.application.bank import IN, OTHER, OUT, BankLine, BankOperationInput
from modern_gl.desktop.session import Session
from modern_gl.i18n import trd


def cash_prefill(
    s: Session,
    account: AccountableAccount,
    employee_id: int,
    day: str,
    amount: int,
    *,
    to_employee: bool,
) -> BankOperationInput:
    """The cash operation for the employee: out of the first cash desk, or into it."""
    desk = next((a for a in s.catalog.leaf_accounts if a.account_type == "cash"), None)
    employee: list[int | None] = [None, None, None]
    employee[account.position - 1] = employee_id
    name = s.catalog.value(employee_id).name
    memo = (
        trd("Выдано под отчёт: {name}", name=name)
        if to_employee
        else trd("Возврат подотчётных сумм: {name}", name=name)
    )
    return BankOperationInput(
        doc_date=day,
        direction=OUT if to_employee else IN,
        account_id=desk.id if desk is not None else None,
        kind=OTHER,
        lines=(BankLine(account.id, amount, tuple(employee)),),
        memo=memo,
    )
