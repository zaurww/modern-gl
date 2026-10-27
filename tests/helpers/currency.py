"""Shared from test_currency.py (moved here: other test modules use it too)."""

from __future__ import annotations

import pytest

from modern_gl.application.ledger import PostingInput
from modern_gl.domain.currency import (
    parse_rate,
)


@pytest.fixture(name="currency_books")
def books(ledger):
    cid = ledger.create_company("ООО Валюта")
    banks = ledger.add_subconto_kind(cid, "bank_account", "Банковские счета")
    parties = ledger.add_subconto_kind(cid, "counterparty", "Контрагенты")
    bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    supplier = ledger.add_subconto_value(cid, parties, "Supplier Ltd")
    acc = {
        "41": ledger.add_account(cid, "41", "Товары", account_class="asset"),
        "51": ledger.add_account(cid, "51", "Расчётный счёт", account_class="asset"),
        "52": ledger.add_account(
            cid, "52", "Валютный счёт", account_class="asset", subconto=[banks], currency=True
        ),
        "60": ledger.add_account(
            cid,
            "60",
            "Поставщики",
            account_class="liability",
            two_sided=True,
            subconto=[parties],
            currency=True,
        ),
        "80": ledger.add_account(cid, "80", "Прибыли и убытки", account_class="equity"),
    }
    usd = ledger.currency_id(cid, "USD")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.set_rate(cid, "USD", "2026-03-20", parse_rate("1.71"))
    ledger.set_rate(cid, "USD", "2026-03-31", parse_rate("1.72"))
    return cid, acc, usd, bank, supplier


def post_example(ledger, books):
    cid, acc, usd, bank, supplier = books
    ledger.post_new(
        cid,
        "2026-03-05",
        [PostingInput(acc["52"], acc["51"], "1700.00", (bank,), (), "", usd, "1000.00")],
    )
    ledger.post_new(
        cid,
        "2026-03-10",
        [PostingInput(acc["41"], acc["60"], "850.00", (), (supplier,), "", usd, "500.00")],
    )
    ledger.post_new(
        cid,
        "2026-03-20",
        [PostingInput(acc["60"], acc["52"], "513.00", (supplier,), (bank,), "", usd, "300.00")],
    )
