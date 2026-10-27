"""Shared from test_conversion.py (moved here: other test modules use it too)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from modern_gl.application.conversion import (
    ConversionFee,
    ConversionInput,
    ConversionSide,
)
from modern_gl.application.queries import load_document
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.currency import parse_rate


@pytest.fixture(name="conversion_firm")
def firm(ledger):
    cid = ledger.create_company("ООО Конвертация")
    banks = ledger.add_subconto_kind(cid, "bank_account", "Банковские счета")
    items = ledger.add_subconto_kind(cid, "other_income", "Прочие доходы и расходы")
    azn_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank AZN")
    usd_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    eur_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank EUR")
    usd, eur = ledger.currency_id(cid, "USD"), ledger.currency_id(cid, "EUR")
    ledger.set_subconto_value_currency(cid, usd_bank, usd)
    ledger.set_subconto_value_currency(cid, eur_bank, eur)
    acc = {
        "51": ledger.add_account(cid, "51", "Расчётный счёт", subconto=[banks]),
        "52": ledger.add_account(cid, "52", "Валютный счёт", subconto=[banks], currency=True),
        "57": ledger.add_account(cid, "57", "Переводы в пути", account_class="asset"),
        "91.1": ledger.add_account(
            cid, "91.1", "Прочие доходы", account_class="revenue", subconto=[items]
        ),
        "91.2": ledger.add_account(
            cid, "91.2", "Прочие расходы", account_class="expense", subconto=[items]
        ),
    }
    for account in ("51", "52"):
        ledger.set_account_class(cid, acc[account], "asset")
    ledger.set_account_role(cid, FX_TRANSIT, acc["57"])
    ledger.set_account_role(cid, FX_GAIN, acc["91.1"])
    ledger.set_account_role(cid, FX_LOSS, acc["91.2"])
    ledger.set_account_role(cid, BANK_FEE, acc["91.2"])
    ledger.set_rate(cid, "USD", "2026-03-02", parse_rate("1.7"))
    ledger.set_rate(cid, "EUR", "2026-03-02", parse_rate("1.85"))
    ledger.set_rate(cid, "USD", "2026-03-03", parse_rate("1.71"))
    return {
        "cid": cid,
        "acc": acc,
        "usd": usd,
        "eur": eur,
        "azn_bank": azn_bank,
        "usd_bank": usd_bank,
        "eur_bank": eur_bank,
    }


def sale(f, **changes) -> ConversionInput:
    data = ConversionInput(
        doc_date="2026-03-02",
        source=ConversionSide(f["acc"]["52"], 100_000, (f["usd_bank"],), f["usd"], "REF-1"),
        target=ConversionSide(f["acc"]["51"], 169_500, (f["azn_bank"],), None, "REF-2"),
        fees=(ConversionFee(f["acc"]["52"], 200, (f["usd_bank"],), f["usd"]),),
        memo="Продажа USD",
    )
    return replace(data, **changes)


def postings(conn, cid, doc_id):
    return [
        (p.debit_account_id, p.credit_account_id, p.amount, p.currency_amount)
        for p in load_document(conn, cid, doc_id).postings
    ]
