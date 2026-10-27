"""Deleting an account or a directory element entered by mistake (D59): only one nothing
refers to; otherwise the message says where it is used and that it can be hidden."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.common import USAGE_TEXTS
from modern_gl.application.inventory import ReceiptLine
from modern_gl.application.ledger import TemplateLine
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.reports_page import ChartPage
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n_az import AZ
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def exists(conn, table: str, row_id: int) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone() is not None


def test_an_unused_account_is_deleted_and_audited(demo, conn):
    wrong = demo.ledger.add_account(demo.company_id, "7210", "Ошибка", account_class="expense")
    demo.ledger.delete_account(demo.company_id, wrong)
    assert not exists(conn, "accounts", wrong)
    audit = conn.execute(
        "SELECT action FROM audit_events WHERE entity = 'account' AND entity_id = ? "
        "ORDER BY id DESC",
        (wrong,),
    ).fetchone()
    assert audit["action"] == "delete"


def test_a_used_account_says_where(demo):
    """201 has postings (document №2 is the first of them); the group 22 has subaccounts;
    an account in a template is named by the template."""
    with pytest.raises(
        ValidationError,
        match=r"счёт 201 нельзя удалить: есть проводки в документе №2\. Его можно скрыть",
    ):
        demo.ledger.delete_account(demo.company_id, demo.acc["201"])
    with pytest.raises(ValidationError, match="у счёта есть субсчета"):
        demo.ledger.delete_account(demo.company_id, demo.acc["22"])
    unused = demo.ledger.add_account(demo.company_id, "7211", "Аренда", account_class="expense")
    demo.ledger.save_template(demo.company_id, "Аренда", [TemplateLine(unused, demo.acc["531"])])
    with pytest.raises(ValidationError, match="он есть в шаблоне «Аренда»"):
        demo.ledger.delete_account(demo.company_id, unused)


def test_a_directory_element_is_deleted_unless_used(demo, conn, ledger):
    """Supplier A has postings; a counterparty with a contract keeps it; an unused one goes."""
    cid = demo.company_id
    kind = ledger.subconto_kind_id(cid, "counterparty")
    with pytest.raises(ValidationError, match="«Поставщик A» нельзя удалить: есть проводки"):
        ledger.delete_subconto_value(cid, demo.supplier_a)
    typo = ledger.add_subconto_value(cid, kind, "Поставщик С")
    ledger.delete_subconto_value(cid, typo)
    assert not exists(conn, "subconto_values", typo)

    contracts = ledger.add_subconto_kind(cid, "contract", "Договоры", owner_kind_id=kind)
    owner = ledger.add_subconto_value(cid, kind, "Гамма")
    ledger.add_subconto_value(cid, contracts, "Договор 1", owner_id=owner)
    with pytest.raises(ValidationError, match="к нему относится «Договор 1»"):
        ledger.delete_subconto_value(cid, owner)


def test_an_item_or_a_warehouse_goes_with_its_element_when_no_document_has_it(shop, conn):
    """«Printer» was bought, so it stays; a new item and a new warehouse go with their
    directory elements. A purchase line's expense subconto (a column without a foreign
    key) keeps its element too."""
    cid = shop.company_id
    unit = conn.execute("SELECT unit_id FROM inventory_items WHERE id = ?", (shop.item,))
    shop.receipt("2026-03-01", "1", "100")
    printer = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    with pytest.raises(
        ValidationError, match="«Printer» нельзя удалить: он есть в складском документе №1"
    ):
        shop.inventory.delete_value(cid, printer)

    scanner = shop.inventory.add_item(cid, "Skaner", unit.fetchone()[0], shop.acc["41"])
    scanner_value = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (scanner,)
    ).fetchone()[0]
    shop.inventory.delete_value(cid, scanner_value)
    assert not exists(conn, "inventory_items", scanner)
    assert not exists(conn, "subconto_values", scanner_value)

    second = shop.inventory.add_warehouse(cid, "Anbar 2")
    second_value = conn.execute(
        "SELECT subconto_value_id FROM warehouses WHERE id = ?", (second,)
    ).fetchone()[0]
    shop.inventory.delete_value(cid, second_value)
    assert not exists(conn, "warehouses", second)

    cost_item = shop.ledger.subconto_kind_id(cid, "cost_item")
    repair = shop.ledger.add_subconto_value(cid, cost_item, "Təmir")
    shop.inventory.create_receipt_draft(
        cid,
        "2026-03-05",
        [
            ReceiptLine(
                None,
                None,
                None,
                "50",
                "Təmir",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            )
        ],
        shop.acc["60"],
        shop.supplier,
    )
    with pytest.raises(ValidationError, match="складском документе №2"):
        shop.inventory.delete_value(cid, repair)


def test_every_usage_text_has_azerbaijani_translation():
    assert [text for text in USAGE_TEXTS.values() if text not in AZ] == []


@pytest.fixture
def yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_chart_and_directory_pages_delete(demo, conn, qtbot, yes):
    cid = demo.company_id
    wrong = demo.ledger.add_account(cid, "7210", "Ошибка", account_class="expense")
    session = Session(conn, demo.ledger, cid, "ООО Тест", Catalog(conn, cid))
    chart = ChartPage(session)
    qtbot.addWidget(chart)
    chart.delete_account(session.catalog.accounts[wrong])
    assert not exists(conn, "accounts", wrong)
    assert wrong not in session.catalog.accounts
    chart.delete_account(session.catalog.accounts[demo.acc["201"]])  # used: stays
    assert exists(conn, "accounts", demo.acc["201"])

    kind = demo.ledger.subconto_kind_id(cid, "counterparty")
    typo = demo.ledger.add_subconto_value(cid, kind, "Поставщик С")
    session.catalog.reload()
    page = DirectoriesPage(session)
    qtbot.addWidget(page)
    page.delete_value(session.catalog.value(typo))
    assert not exists(conn, "subconto_values", typo)
