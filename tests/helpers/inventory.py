"""Shared from test_inventory.py (moved here: other test modules use it too)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from modern_gl.application.inventory import (
    Inventory,
)


@dataclass
class InventoryDemo:
    inventory: Inventory
    company_id: int
    item: int
    other_item: int
    main: int
    reserve: int
    inventory_account: int
    payable_account: int
    expense_account: int
    supplier: int


@pytest.fixture
def inventory_demo(ledger, conn) -> InventoryDemo:
    company_id = ledger.create_company("Склад")
    item_kind = ledger.add_subconto_kind(company_id, "item", "Товары")
    warehouse_kind = ledger.add_subconto_kind(company_id, "warehouse", "Склады")
    counterparty_kind = ledger.add_subconto_kind(company_id, "counterparty", "Контрагенты")
    inventory_account = ledger.add_account(
        company_id,
        "41",
        "Товары",
        subconto=[item_kind, warehouse_kind],
        account_class="asset",
    )
    payable_account = ledger.add_account(
        company_id,
        "60",
        "Поставщики",
        subconto=[counterparty_kind],
        account_class="liability",
    )
    expense_account = ledger.add_account(company_id, "46", "Себестоимость", account_class="expense")
    supplier = ledger.add_subconto_value(company_id, counterparty_kind, "Поставщик")
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(company_id, "шт", "Штука", precision=3)
    item = inventory.add_item(company_id, "Товар A", unit, inventory_account, "A")
    other_item = inventory.add_item(company_id, "Товар B", unit, inventory_account, "B")
    main = inventory.add_warehouse(company_id, "Основной", "MAIN")
    reserve = inventory.add_warehouse(company_id, "Резервный", "RESERVE")
    return InventoryDemo(
        inventory,
        company_id,
        item,
        other_item,
        main,
        reserve,
        inventory_account,
        payable_account,
        expense_account,
        supplier,
    )
