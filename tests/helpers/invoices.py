"""Shared from test_invoices.py (moved here: other test modules use it too)."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger
from modern_gl.infrastructure.db import connect
from tests.helpers.advances import add_advance_accounts


@pytest.fixture(name="invoice_firm")
def firm():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    add_advance_accounts(ledger, cid)
    kind = {c: ledger.subconto_kind_id(cid, c) for c in ("counterparty", "contract")}
    v = {
        "Альфа": ledger.add_subconto_value(cid, kind["counterparty"], "Альфа"),
        "Бета": ledger.add_subconto_value(cid, kind["counterparty"], "Бета"),
        "Аренда": ledger.add_subconto_value(
            cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"
        ),
        "Kapital": ledger.add_subconto_value(
            cid, ledger.subconto_kind_id(cid, "bank_account"), "Kapital"
        ),
    }
    v["Д-1"] = ledger.add_subconto_value(cid, kind["contract"], "Д-1", owner_id=v["Альфа"])
    v["Общий"] = ledger.add_subconto_value(cid, kind["contract"], "Общий")
    ledger.set_subconto_value_tax(cid, v["Альфа"], "1234567890")
    cat = Catalog(conn, cid)
    acc = {code: a.id for code, a in cat.by_code.items()}
    yield conn, ledger, cid, acc, v
    conn.close()
