"""The warehouse finds a company's rows (account, directory element, currency, kind of
directory) exactly as the ledger does: one set of lookups in `LedgerBase` (debt 12)."""

from __future__ import annotations

import pytest

from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.errors import NotFoundError


@pytest.fixture
def two_companies(ledger, conn):
    ours = ledger.create_company("ООО Наша")
    other = ledger.create_company("ООО Чужая")
    kind = ledger.add_subconto_kind(other, "counterparty", "Контрагенты")
    foreign = {
        "account": ledger.add_account(other, "60", "Поставщики"),
        "value": ledger.add_subconto_value(other, kind, "ALFA MMC"),
        "currency": ledger.currency_id(other, "USD"),
    }
    return Inventory(conn), ledger, ours, foreign


def test_inventory_uses_the_ledgers_lookups(two_companies):
    inventory, *_ = two_companies
    assert isinstance(inventory, LedgerBase)


def test_rows_of_another_company_are_not_found_alike(two_companies):
    """The same messages from the warehouse and from the ledger; an id is not shown."""
    inventory, ledger, ours, foreign = two_companies
    cases = [
        ("_account", foreign["account"], r"^счёт не найден$"),
        ("_subconto_value", foreign["value"], r"^элемент справочника не найден$"),
        ("_currency", foreign["currency"], r"^валюта не найдена$"),
    ]
    for method, row_id, message in cases:
        for side in (inventory, ledger):
            with pytest.raises(NotFoundError, match=message):
                getattr(side, method)(ours, row_id)
    for side in (inventory, ledger):
        with pytest.raises(NotFoundError, match=r"^вид субконто no_such_kind не найден$"):
            side._kind_id(ours, "no_such_kind")
