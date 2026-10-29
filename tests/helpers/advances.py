"""Advance accounts as the templates had them before one settlement account (D-new): an
old company keeps them, so the tests of what they do add them — 60.2 / 62.2 under 60 / 62
of the 1C chart, 61 / 64 of the classic one."""

from __future__ import annotations

from modern_gl.domain.currency import CURRENCY_OPTIONAL


def add_advance_accounts(ledger, cid) -> tuple[int, int]:
    """The accounts of the advances paid and received with their roles; their ids."""
    kinds = [ledger.subconto_kind_id(cid, k) for k in ("counterparty", "contract")]
    one_c = ledger.conn.execute(
        "SELECT 1 FROM accounts WHERE company_id = ? AND code = '60.1'", (cid,)
    ).fetchone()
    if one_c:
        places = (("60.2", "Авансы выданные", "60"), ("62.2", "Авансы полученные", "62"))
        currency = CURRENCY_OPTIONAL
    else:
        places = (
            ("61", "Расчёты по авансам выданным", None),
            ("64", "Расчёты по авансам полученным", None),
        )
        currency = None
    made = []
    for (code, name, parent), role in zip(
        places, ("advance_paid", "advance_received"), strict=True
    ):
        account = ledger.add_account(
            cid,
            code,
            name,
            parent=parent,
            subconto=kinds,
            account_type=role,
            two_sided=True,
            currency=currency,
        )
        ledger.set_account_role(cid, role, account)
        made.append(account)
    return made[0], made[1]
