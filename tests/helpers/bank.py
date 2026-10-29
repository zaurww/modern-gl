"""Shared from test_bank.py (moved here: other test modules use it too)."""

from __future__ import annotations

import pytest

from modern_gl.application.bank import (
    FEE,
    OUT,
    BankLine,
    BankOperationInput,
    load_bank_operation,
)
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import load_document
from modern_gl.domain.currency import parse_rate
from tests.helpers.advances import add_advance_accounts


@pytest.fixture(name="bank_firm")
def firm(ledger):
    cid = ledger.create_company("ООО Банк")
    apply_chart_template(ledger, cid, "1c77", "ru")
    add_advance_accounts(ledger, cid)
    kind = {
        code: ledger.subconto_kind_id(cid, code)
        for code in (
            "bank_account",
            "counterparty",
            "contract",
            "cost_item",
            "other_income",
            "employee",
        )
    }
    acc = {
        code: ledger.account_id(cid, code)
        for code in ("51", "52", "55", "26", "60.1", "62.1", "68.1", "70", "80", "91.2")
    }
    usd = ledger.currency_id(cid, "USD")
    v = {
        "azn": ledger.add_subconto_value(cid, kind["bank_account"], "Kapital AZN"),
        "usd": ledger.add_subconto_value(cid, kind["bank_account"], "Kapital USD"),
        "pasha": ledger.add_subconto_value(cid, kind["bank_account"], "PAŞA AZN"),
        "alfa": ledger.add_subconto_value(cid, kind["counterparty"], "ALFA MMC"),
        "beta": ledger.add_subconto_value(cid, kind["counterparty"], "BETA MMC"),
        "owner": ledger.add_subconto_value(cid, kind["counterparty"], "Учредитель"),
        "rent": ledger.add_subconto_value(cid, kind["cost_item"], "Аренда"),
        "fee": ledger.add_subconto_value(cid, kind["other_income"], "Комиссия банка"),
    }
    v["contract"] = ledger.add_subconto_value(
        cid, kind["contract"], "Договор 1", owner_id=v["alfa"]
    )
    v["contract_b"] = ledger.add_subconto_value(
        cid, kind["contract"], "Договор 2", owner_id=v["beta"]
    )
    ledger.set_subconto_value_currency(cid, v["usd"], usd)
    ledger.set_subconto_value_tax(cid, v["alfa"], "1234567890")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    for doc_date, posting in (
        ("2026-03-01", PostingInput(acc["51"], acc["80"], "10000", [v["azn"]], [v["owner"]])),
        (
            "2026-03-01",
            PostingInput(acc["52"], acc["80"], "1700", [v["usd"]], [v["owner"]], "", usd, "1000"),
        ),
        (
            "2026-03-02",
            PostingInput(
                acc["26"],
                acc["60.1"],
                "1180",
                [v["rent"]],
                [v["alfa"], v["contract"]],
                invoice="MT001",
            ),
        ),
    ):
        ledger.post_new(cid, doc_date, [posting])
    return {"cid": cid, "acc": acc, "v": v, "usd": usd, "kind": kind}


def usd_fee(f) -> BankOperationInput:
    acc, v = f["acc"], f["v"]
    return BankOperationInput(
        doc_date="2026-03-07",
        direction=OUT,
        account_id=acc["52"],
        subconto=(v["usd"],),
        currency_id=f["usd"],
        kind=FEE,
        lines=(BankLine(acc["91.2"], 200, (v["fee"],)),),
        memo="Комиссия банка",
    )


def postings(ledger, f, operation_id):
    op = load_bank_operation(ledger.conn, f["cid"], operation_id)
    return load_document(ledger.conn, f["cid"], op.document_id).postings
