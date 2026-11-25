"""«Куда» of a purchase line has a third choice: an expense of a batch (the cost of goods).
The account where it waits (15) is put in by the program — nobody has to know it.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLineEdit

from modern_gl.application.catalog import Catalog
from modern_gl.application.trade_batch import OpenLines
from modern_gl.desktop.batch_post_dialog import BatchPostDialog
from modern_gl.desktop.inventory_document_page import AMOUNT, ITEM, WAREHOUSE, InventoryDocumentPage
from modern_gl.desktop.inventory_document_page.columns import (
    EXPENSE,
    KIND,
    LANDED,
    PRICE,
    QUANTITY,
    SERVICE,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import waiting_lines
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def purchase(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    return page


def broker_line(page: InventoryDocumentPage, amount: int = 20_000, row: int = 0) -> None:
    if row:
        page.model.insert_row()
    page._make_service(row, "Broker xidməti")
    page.model.setData(page.model.index(row, page.model.columns.index(AMOUNT)), amount)


def cell(page: InventoryDocumentPage, row: int, key: str):
    return page.model.index(row, page.model.columns.index(key))


def test_an_expense_of_a_batch_waits_on_its_account(shop, conn, qtbot):
    """The broker's service 200.00, ƏDV 18% 36.00, «Куда» — the cost of goods:
    Dt 15 / Kt 60 200.00, Dt 19 / Kt 60 36.00; 200.00 waits for a batch."""
    page = purchase(shop, conn, qtbot)
    model = page.model
    broker_line(page)
    assert model.rows[0].expense_account_id is None
    assert model.data(cell(page, 0, KIND)) == tr("Счёт")

    assert model.setData(cell(page, 0, KIND), LANDED)
    assert model.rows[0].expense_account_id == shop.acc["15"]
    assert model.data(cell(page, 0, KIND)) == tr("Доп. расход")

    model.set_party(shop.acc["60"], [*shop.supplier, None])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert sorted(p[:3] for p in shop.postings(page.doc.id)) == [
        ("15", "60", 20_000),
        ("19", "60", 3_600),
    ]
    (waiting,) = waiting_lines(conn, shop.company_id)
    assert (waiting.left, waiting.waits) == (20_000, True)


def test_the_list_names_what_the_choice_is_for(shop, conn, qtbot):
    """The list says «(себестоимость товара)»; typed in part, it is found."""
    page = purchase(shop, conn, qtbot)
    broker_line(page)
    index = cell(page, 0, KIND)
    labels = [label for _, label in page.model.choices(0, KIND)]
    assert labels == [tr("Склад"), tr("Счёт"), tr("Доп. расход (себестоимость товара)")]
    page.delegate.setModelData(QLineEdit(tr("Доп. расход")), page.model, index)
    assert page.model.rows[0].expense_account_id == shop.acc["15"]


def test_the_choice_goes_to_the_other_lines_without_an_account(shop, conn, qtbot):
    """A broker's e-qaimə of two lines: the second one, still without an account, follows."""
    page = purchase(shop, conn, qtbot)
    broker_line(page)
    broker_line(page, 5_000, row=1)
    page.model.rows[1].expense_account_id = None
    page.model.setData(cell(page, 0, KIND), LANDED)
    assert [row.expense_account_id for row in page.model.rows] == [shop.acc["15"]] * 2


def test_back_to_an_account_asks_for_one(shop, conn, qtbot):
    """«Счёт» picked on an expense of a batch: the waiting account is taken away."""
    page = purchase(shop, conn, qtbot)
    broker_line(page)
    page.model.setData(cell(page, 0, KIND), LANDED)
    assert page.model.setData(cell(page, 0, KIND), SERVICE)
    assert page.model.rows[0].expense_account_id is None
    assert page.model.data(cell(page, 0, KIND)) == tr("Счёт")


def test_the_account_typed_by_hand_is_the_same_choice(shop, conn, qtbot):
    """One source of truth: 15 picked in «Счёт» is an expense of a batch; 44 is not."""
    page = purchase(shop, conn, qtbot)
    broker_line(page)
    page.model.setData(cell(page, 0, EXPENSE), shop.acc["15"])
    assert page.model.data(cell(page, 0, KIND)) == tr("Доп. расход")
    page.model.setData(cell(page, 0, EXPENSE), shop.acc["44"])
    assert page.model.data(cell(page, 0, KIND)) == tr("Счёт")


def test_a_goods_line_becomes_an_expense_of_a_batch(shop, conn, qtbot):
    page = purchase(shop, conn, qtbot)
    model = page.model
    model.setData(cell(page, 0, ITEM), shop.item)
    model.setData(cell(page, 0, WAREHOUSE), shop.main)
    assert model.setData(cell(page, 0, KIND), LANDED)
    row = model.rows[0]
    assert (row.item_id, row.memo, row.expense_account_id) == (None, "Printer", shop.acc["15"])


def test_a_chart_without_the_account_gets_one(shop, conn, qtbot):
    """An older company: no role and no 15 — the choice makes the account and keeps it."""
    shop.ledger.set_account_role(shop.company_id, BATCH_EXPENSES_ACCOUNT, None)
    conn.execute("UPDATE accounts SET code = '15X' WHERE id = ?", (shop.acc["15"],))
    conn.execute("UPDATE accounts SET account_type = NULL WHERE id = ?", (shop.acc["15"],))
    page = purchase(shop, conn, qtbot)
    broker_line(page)
    page.model.setData(cell(page, 0, KIND), LANDED)
    made = shop.ledger.account_role(shop.company_id, BATCH_EXPENSES_ACCOUNT)
    assert made not in (None, shop.acc["15"])
    assert page.model.rows[0].expense_account_id == made
    assert str(page.model.data(cell(page, 0, EXPENSE))).startswith("15")


def test_drafts_posted_at_once_offer_the_choice_first(shop, conn, qtbot):
    """«Провести черновики»: the account list starts with the expense of a batch."""
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    dialog = BatchPostDialog(session, 1, "", OpenLines("receipt", 1, None, shop.acc["60"]), [])
    qtbot.addWidget(dialog)
    assert dialog.account is not None
    assert dialog.account.itemText(0) == tr("Доп. расход (себестоимость товара)")
    assert dialog.account.itemData(0) == shop.acc["15"]


def test_a_new_service_stops_at_where_it_goes_first(shop, conn, qtbot):
    """After «it is a service» the cursor is in «Куда», not in the account: the choice
    that needs no account to be known comes first."""
    page = purchase(shop, conn, qtbot)
    page.show()
    qtbot.waitExposed(page)
    page._make_service(0, "Broker xidməti")
    assert page.table.currentIndex().column() == page.model.columns.index(KIND)


def test_a_cell_error_goes_away_with_the_next_value(shop, conn, qtbot):
    """A price before the quantity is refused with a message; the quantity typed, the
    message has nothing more to say (seen in a live test: it stayed on the screen)."""
    page = purchase(shop, conn, qtbot)
    page.show()
    qtbot.waitExposed(page)
    broker_line(page)
    page.model.rows[0].amount = None
    page.delegate.setModelData(QLineEdit("200"), page.model, cell(page, 0, PRICE))
    assert not page.error.isHidden() and page.error.text() == tr("сначала укажите количество")
    page.model.setData(cell(page, 0, QUANTITY), 1_000_000)
    assert page.error.isHidden()
