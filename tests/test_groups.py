"""Groups (folders) in directories, as in 1C (D60): «Kabellər» holds its items. A group
is never chosen on a posting; items and counterparties move between groups freely, and
an item's unit and stock account change while no document has it."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QInputDialog

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import ReceiptLine
from modern_gl.application.ledger import PostingInput
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.inventory_page import InventoryPage, StockGroup
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from tests.test_sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def test_a_group_holds_elements_and_never_goes_on_a_posting(demo, ledger):
    cid = demo.company_id
    kind = ledger.subconto_kind_id(cid, "counterparty")
    foreign = ledger.add_subconto_group(cid, kind, "Иностранные")
    europe = ledger.add_subconto_group(cid, kind, "Европа", parent_id=foreign)
    gmbh = ledger.add_subconto_value(cid, kind, "Müller GmbH", parent_id=europe)
    ledger.set_subconto_value_parent(cid, demo.supplier_b, foreign)

    catalog = Catalog(ledger.conn, cid)
    assert [(depth, v.name) for depth, v in catalog.tree(kind)] == [
        (0, "Иностранные"),
        (1, "Европа"),
        (2, "Müller GmbH"),
        (1, "Поставщик B"),
        (0, "Поставщик A"),
    ]
    assert catalog.group_path(gmbh) == "Иностранные / Европа"
    assert [v.name for v in catalog.values(kind)] == ["Müller GmbH", "Поставщик A", "Поставщик B"]

    with pytest.raises(ValidationError, match="«Иностранные» — группа, выберите элемент"):
        ledger.post_new(
            cid,
            "2026-03-01",
            [PostingInput(demo.acc["201"], demo.acc["531"], "10", (), (foreign,))],
        )
    with pytest.raises(ValidationError, match="группу нельзя перенести в неё саму"):
        ledger.set_subconto_value_parent(cid, foreign, europe)
    with pytest.raises(ValidationError, match="«Müller GmbH» — не группа"):
        ledger.add_subconto_value(cid, kind, "Ошибка", parent_id=gmbh)
    with pytest.raises(ValidationError, match="к нему относится «Поставщик B»"):
        ledger.delete_subconto_value(cid, foreign)


def test_stock_balances_by_group_and_an_item_changed_while_unused(shop, conn):
    """Printer (no group, 1 for 100.00) and Kabel (in «Kabellər», 2 for 30.00): the list
    goes by group, the items without one last. Kabel's unit changes before it is bought,
    not after."""
    cid = shop.company_id
    kind = shop.ledger.subconto_kind_id(cid, "item")
    cables = shop.ledger.add_subconto_group(cid, kind, "Kabellər")
    unit = conn.execute(
        "SELECT unit_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    metre = shop.inventory.add_unit(cid, "m", "Metr", precision=2)
    cable = shop.inventory.add_item(cid, "Kabel", unit, shop.acc["41"], group_id=cables)
    shop.inventory.update_item(cid, cable, metre, shop.acc["41"])
    shop.receipt("2026-03-01", "1", "100")
    shop.inventory.post_receipt(
        cid,
        "2026-03-02",
        [ReceiptLine(cable, shop.main, "2", "30")],
        shop.acc["60"],
        shop.supplier,
    )
    balances = stock_balances(conn, cid)
    assert [(b.item_name, b.group, b.amount) for b in balances] == [
        ("Kabel", "Kabellər", 3_000),
        ("Printer", "", 10_000),
    ]
    with pytest.raises(ValidationError, match="единицу и счёт товара менять нельзя"):
        shop.inventory.update_item(cid, cable, unit, shop.acc["41"])


def test_directories_page_makes_a_group_and_puts_elements_in_it(demo, conn, qtbot, monkeypatch):
    cid = demo.company_id
    session = Session(conn, demo.ledger, cid, "ООО Тест", Catalog(conn, cid))
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    kind = demo.ledger.subconto_kind_id(cid, "counterparty")
    page.refresh(select_kind=kind)
    monkeypatch.setattr(page, "_ask", lambda *a, **k: "Иностранные")
    page.add_group()
    group = next(v for v in session.catalog.all_values(kind) if v.is_group)
    assert page.model.rows[0].id == group.id  # groups first, in bold
    assert page.model.emphasis(page.model.rows[0])

    page.table.setCurrentIndex(page.model.index(0, 0))  # the group chosen: a new one goes in
    monkeypatch.setattr(page, "_detailed", lambda kind_id: False)
    monkeypatch.setattr(page, "_ask", lambda *a, **k: "Müller GmbH")
    page.add_value()
    gmbh = next(v for v in session.catalog.all_values(kind) if v.name == "Müller GmbH")
    assert gmbh.parent_id == group.id

    supplier_a = session.catalog.value(demo.supplier_a)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("Иностранные", True))
    page.move_value(supplier_a)
    assert session.catalog.value(demo.supplier_a).parent_id == group.id
    names = [page.model.index(r, 0).data().strip(" ") for r in range(page.model.rowCount())]
    assert names[:3] == ["Иностранные   2", "Müller GmbH", "Поставщик A"]


def test_inventory_page_shows_group_headers_with_their_value(shop, conn, qtbot):
    cid = shop.company_id
    kind = shop.ledger.subconto_kind_id(cid, "item")
    office = shop.ledger.add_subconto_group(cid, kind, "Ofis texnikası")
    value = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    shop.ledger.set_subconto_value_parent(cid, value, office)
    shop.receipt("2026-03-01", "2", "240")
    session = Session(conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid))
    page = InventoryPage(session)
    qtbot.addWidget(page)
    assert page.model.rows[0] == StockGroup("Ofis texnikası", 24_000)
    assert page.model.rows[1].item_name == "Printer"
