"""The account a new line or bank account starts with — by role or type, so both charts
get the right one (debt 11): the codes differ between them."""

from __future__ import annotations

import pytest

from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.default_accounts import (
    CARD_ACCOUNT,
    COST_OF_GOODS,
    CURRENCY_ACCOUNT,
    CURRENT_ACCOUNT,
    CUSTOMER,
    EXCHANGE_GAIN,
    EXCHANGE_LOSS,
    RETAINED_EARNINGS,
    SUPPLIER,
    VAT_DEPOSIT_ACCOUNT,
    default_account,
)

PURPOSES = [
    SUPPLIER,
    CUSTOMER,
    RETAINED_EARNINGS,
    CURRENT_ACCOUNT,
    CURRENCY_ACCOUNT,
    VAT_DEPOSIT_ACCOUNT,
    CARD_ACCOUNT,
]


def codes(ledger, cid) -> dict[str, str | None]:
    found = {p: default_account(ledger, cid, p) for p in PURPOSES}
    code = {
        r["id"]: r["code"]
        for r in ledger.conn.execute("SELECT id, code FROM accounts WHERE company_id = ?", (cid,))
    }
    return {p: code.get(a) if a else None for p, a in found.items()}


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "classic",
            {
                SUPPLIER: "60",
                CUSTOMER: "62",
                RETAINED_EARNINGS: "88",
                CURRENT_ACCOUNT: "51",
                CURRENCY_ACCOUNT: "52",
                VAT_DEPOSIT_ACCOUNT: "54",
                CARD_ACCOUNT: "51",  # no 55 in the classic chart: the current account
            },
        ),
        (
            "1c77",
            {
                SUPPLIER: "60.1",  # 60 is a group in 1C 7.7
                CUSTOMER: "62.1",
                RETAINED_EARNINGS: "84",
                CURRENT_ACCOUNT: "51",
                CURRENCY_ACCOUNT: "52",
                VAT_DEPOSIT_ACCOUNT: "54",
                CARD_ACCOUNT: "55",
            },
        ),
    ],
)
def test_default_accounts_of_both_charts(ledger, template, expected):
    cid = ledger.create_company(template)
    apply_chart_template(ledger, cid, template)
    assert codes(ledger, cid) == expected


def test_roles_name_the_written_off_goods_and_exchange_differences(ledger):
    cid = ledger.create_company("classic")
    apply_chart_template(ledger, cid, "classic")
    by_id = {
        r["id"]: r["code"]
        for r in ledger.conn.execute("SELECT id, code FROM accounts WHERE company_id = ?", (cid,))
    }
    assert by_id[default_account(ledger, cid, COST_OF_GOODS)] == "46"
    assert by_id[default_account(ledger, cid, EXCHANGE_GAIN)] == "80"  # Прибыли и убытки
    assert by_id[default_account(ledger, cid, EXCHANGE_LOSS)] == "80"
