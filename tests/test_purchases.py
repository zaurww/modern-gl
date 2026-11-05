"""«Поступление / Alış» of services and fixed assets: lines without an item.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPersistentModelIndex, Qt

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import QUANTITY_FACTOR, STANDARD_VAT_RATE, ReceiptLine
from modern_gl.desktop.inventory_document_page import (
    ACCOUNT,
    AMOUNT,
    ESC1,
    EXPENSE,
    ITEM,
    SC1,
    SC2,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from modern_gl.reporting.invoices import invoice_report
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def values(shop: Shop, kind: str, *names: str) -> list[int]:
    kind_id = shop.ledger.subconto_kind_id(shop.company_id, kind)
    return [shop.ledger.add_subconto_value(shop.company_id, kind_id, name) for name in names]


def purchase(shop: Shop, lines: list[ReceiptLine], **kwargs) -> int:
    return shop.inventory.post_receipt(
        shop.company_id,
        "2026-03-05",
        lines,
        shop.acc["60"],
        shop.supplier,
        "Alış",
        vat_rate=STANDARD_VAT_RATE,
        **kwargs,
    )


def test_purchase_of_goods_a_service_and_a_fixed_asset(shop, conn):
    """One e-qaimə MT2603000111 from the supplier:
      5 printers      100.00 + VAT 18.00   Dt 41 [Printer, Əsas anbar] / Kt 60
      repair service   50.00 + VAT  9.00   Dt 26 [Təmir] / Kt 60
      laptop        1 000.00 + VAT 180.00  Dt 08 [Noutbuk] / Kt 60
      VAT 207.00 in one posting            Dt 19 [supplier] / Kt 60
    The supplier is owed 1 357.00 = 1 150.00 + 207.00; only the printers are in stock."""
    (repair,) = values(shop, "cost_item", "Təmir")
    (laptop,) = values(shop, "fixed_asset", "Noutbuk Dell")
    receipt = purchase(
        shop,
        [
            ReceiptLine(shop.item, shop.main, "5", "100", vat_amount="18"),
            ReceiptLine(
                None,
                None,
                None,
                "50",
                "Printerin təmiri",
                vat_amount="9",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            ),
            ReceiptLine(
                None,
                None,
                "1",
                "1000",
                "Noutbuk",
                vat_amount="180",
                expense_account_id=shop.acc["08"],
                expense_subconto=[laptop],
            ),
        ],
        invoice="MT2603000111",
    )
    assert shop.postings(receipt) == [
        ("41", "60", 10_000, "", "MT2603000111"),
        ("26", "60", 5_000, "Printerin təmiri", "MT2603000111"),
        ("08", "60", 100_000, "Noutbuk", "MT2603000111"),
        ("19", "60", 20_700, "НДС", "MT2603000111"),
    ]
    debits = conn.execute(
        "SELECT dt_sc1 FROM postings WHERE debit_account_id IN (?, ?) ORDER BY line_no",
        (shop.acc["26"], shop.acc["08"]),
    ).fetchall()
    assert [row[0] for row in debits] == [repair, laptop]
    (balance,) = stock_balances(conn, shop.company_id)
    assert (balance.quantity, balance.amount) == (5 * QUANTITY_FACTOR, 10_000)

    doc = shop.inventory.load_document(shop.company_id, receipt)
    service = doc.lines[1]
    assert (service.item_id, service.warehouse_id, service.quantity) == (None, None, 0)
    assert service.cost_account_id == shop.acc["26"]
    assert service.cost_subconto == (repair, None, None)
    assert doc.lines[2].quantity == QUANTITY_FACTOR

    (row,) = invoice_report(conn, shop.company_id, "2026-03-01", "2026-03-31")
    assert (row.credit, row.vat) == (135_700, 20_700)


def test_expense_line_is_checked_when_posted(shop):
    """A draft may lack the account; posting names it. The memo says what was bought."""
    draft = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-05",
        [ReceiptLine(None, None, None, "50", "Təmir")],
        shop.acc["60"],
        shop.supplier,
    )
    with pytest.raises(ValidationError, match="строка 1: не указан счёт затрат"):
        shop.inventory.post_document(shop.company_id, draft)
    shop.inventory.update_receipt_draft(
        shop.company_id,
        draft,
        "2026-03-05",
        [ReceiptLine(None, None, None, "50", expense_account_id=shop.acc["26"])],
        shop.acc["60"],
        shop.supplier,
    )
    with pytest.raises(ValidationError, match="укажите товар или что куплено"):
        shop.inventory.post_document(shop.company_id, draft)
    with pytest.raises(ValidationError, match="строка 1: не указан товар"):
        shop.inventory.post_receipt(
            shop.company_id,
            "2026-03-05",
            [ReceiptLine(None, None, None, "50", "Təmir", expense_account_id=shop.acc["26"])],
            shop.acc["60"],
            shop.supplier,
            opening=True,
        )


def test_expense_line_in_a_currency_receipt(shop, conn):
    """A service from abroad, 100.00 USD at 1.70: Dt 26 / Kt 60 170.00 (100.00 USD)."""
    usd = shop.ledger.currency_id(shop.company_id, "USD")
    (consulting,) = values(shop, "cost_item", "Konsaltinq")
    receipt = shop.inventory.post_receipt(
        shop.company_id,
        "2026-03-05",
        [
            ReceiptLine(
                None,
                None,
                None,
                None,
                "Konsaltinq",
                currency_amount="100",
                expense_account_id=shop.acc["26"],
                expense_subconto=[consulting],
            )
        ],
        shop.acc["60"],
        shop.supplier,
        currency_id=usd,
        currency_rate="1.7",
    )
    gl = shop.inventory.load_document(shop.company_id, receipt).gl_document_id
    posting = conn.execute("SELECT * FROM postings WHERE document_id = ?", (gl,)).fetchone()
    assert (posting["debit_account_id"], posting["amount"]) == (shop.acc["26"], 17_000)
    assert (posting["currency_id"], posting["currency_amount"]) == (usd, 10_000)


def test_receipt_page_buys_a_service(shop, conn, qtbot, monkeypatch):
    """A name that is no item becomes a service line: the expense account columns appear,
    the line posts Dt 26 [Təmir] / Kt 60 50.00 with VAT 9.00."""
    (repair,) = values(shop, "cost_item", "Təmir")
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    expense_column = model.columns.index(EXPENSE)
    # «Счёт» is there from the start: a goods line shows its item's stock account in it
    assert not page.table.isColumnHidden(expense_column)
    assert page.table.isColumnHidden(model.columns.index(ESC1))  # goods only so far

    monkeypatch.setattr(page, "_service_or_item", lambda text: "service")
    page._create_item(QPersistentModelIndex(model.index(0, 0)), "Printerin təmiri")
    assert not page.table.isColumnHidden(expense_column)
    assert page.table.currentIndex().column() == expense_column
    assert model.data(model.index(0, model.columns.index(ITEM))) == "Printerin təmiri"
    assert not model.flags(model.index(0, model.columns.index(WAREHOUSE)))

    def put(key: str, value) -> None:
        assert model.setData(model.index(0, model.columns.index(key)), value)

    put(EXPENSE, shop.acc["26"])
    assert not page.table.isColumnHidden(model.columns.index(ESC1))
    put(ESC1, repair)
    put(AMOUNT, 5_000)
    put(ACCOUNT, shop.acc["60"])
    put(SC1, shop.supplier[0])
    put(SC2, shop.supplier[1])
    assert model.rows[0].vat_amount == 900

    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("26", "60", 5_000), ("19", "60", 900)]
    assert page.model.rows[0].expense_subconto[0] == repair  # loaded back
    assert not page.table.isColumnHidden(expense_column)


def test_a_purchase_posts_without_a_contract(shop, conn, qtbot):
    """Many suppliers have no contract, only the e-qaimə: the line posts with the
    counterparty alone. Repair 50.00 + VAT 9.00: Dt 26 / Kt 60 50.00, Dt 19 / Kt 60 9.00,
    so the supplier is owed 59.00 under «not given» in the ОСВ by contract. Without the
    counterparty it still does not post."""
    from modern_gl.reporting.reports import subconto_balance

    (repair,) = values(shop, "cost_item", "Təmir")
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    page._make_service(0, "Printerin təmiri")
    model = page.model

    def put(key: str, value) -> None:
        assert model.setData(model.index(0, model.columns.index(key)), value)

    put(EXPENSE, shop.acc["26"])
    put(ESC1, repair)
    put(AMOUNT, 5_000)
    put(ACCOUNT, shop.acc["60"])
    assert not page.save(post=True)
    assert page.error.text() == "Укажите поставщика"  # at the header's field
    put(SC1, shop.supplier[0])  # the contract (SC2) stays empty
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("26", "60", 5_000), ("19", "60", 900)]
    by_contract = subconto_balance(
        conn, shop.company_id, "60", "2026-01-01", "2026-12-31", position=2
    )
    assert [(r.name, r.closing_ct) for r in by_contract] == [("<не указано>", 5_900)]


def test_the_name_of_a_line_keeps_its_room_and_shows_whole_when_edited(shop, conn, qtbot):
    """In a narrow window the name keeps ITEM_MIN px (the account and subconto give up
    width); its editor grows over the next cells to show a long e-qaimə name whole."""
    from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit

    from modern_gl.desktop.inventory_document_page import ITEM_MIN

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    long_name = (
        "2026-cı ilin yanvar ayı üçün mühasibat xidmətləri, vergi bəyannamələrinin "
        "və statistika hesabatlarının hazırlanması"
    )
    page._make_service(0, long_name)
    page.resize(1100, 600)
    page.show()
    qtbot.waitExposed(page)
    table, column = page.table, page.model.columns.index(ITEM)
    assert table.columnWidth(column) >= ITEM_MIN
    for open_editor in table.findChildren(QLineEdit):  # _make_service went on to the account
        table.closeEditor(open_editor, QAbstractItemDelegate.EndEditHint.NoHint)
    index = page.model.index(0, column)
    table.setCurrentIndex(index)
    table.edit(index)
    editor = next(e for e in table.findChildren(QLineEdit) if e.isVisible())
    assert editor is not None and editor.text() == long_name
    assert editor.width() > table.columnWidth(column)
    editor.setText("Mühasibat xidmətləri")
    page.delegate.setModelData(editor, page.model, index)  # corrected: still a service
    assert page.model.is_service(0)
    assert page.model.rows[0].memo == "Mühasibat xidmətləri"


def test_a_line_without_an_item_never_goes_to_a_stock_account(shop, conn):
    """A service bought onto 41 [Printer, Əsas anbar] would show 50.00 of goods in the GL
    that the warehouse does not have: it does not post, the message says to pick the item.
    A draft (an e-qaimə taken «as last time») keeps it until then."""
    printer = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    main = conn.execute(
        "SELECT subconto_value_id FROM warehouses WHERE id = ?", (shop.main,)
    ).fetchone()[0]
    line = ReceiptLine(
        None,
        None,
        None,
        "50",
        "Statik İP",
        expense_account_id=shop.acc["41"],
        expense_subconto=[printer, main],
    )
    with pytest.raises(ValidationError, match="строка 1: счёт 41 складской — выберите товар"):
        purchase(shop, [line])
    draft = shop.inventory.create_receipt_draft(
        shop.company_id, "2026-03-05", [line], shop.acc["60"], shop.supplier
    )
    with pytest.raises(ValidationError, match="счёт 41 складской"):
        shop.inventory.post_document(shop.company_id, draft)
    assert conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == 0
    assert stock_balances(conn, shop.company_id) == []


def test_a_service_purchase_has_no_warehouse_column_and_names_its_subconto(shop, conn, qtbot):
    """Services only: no «Склад» and «Ед.», they come back with a line of goods. The
    expense list has no stock account (41). The supplier's second subconto column is
    named by its directory, «Договоры»."""
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    warehouse = model.columns.index(WAREHOUSE)
    assert not page.table.isColumnHidden(warehouse)  # a new document starts as goods
    page._make_service(0, "Statik İP")
    assert page.table.isColumnHidden(warehouse)
    accounts = {account_id for account_id, _ in model.choices(0, EXPENSE)}
    assert shop.acc["26"] in accounts and shop.acc["41"] not in accounts

    assert model.setData(model.index(0, model.columns.index(ACCOUNT)), shop.acc["60"])
    kind = shop.ledger.subconto_kind_id(shop.company_id, "contract")
    assert (
        model.headerData(model.columns.index(SC2), Qt.Orientation.Horizontal)
        == (session.catalog.kinds[kind])
    )

    model.insert_row()
    assert model.setData(model.index(1, model.columns.index(ITEM)), shop.item)
    assert not page.table.isColumnHidden(warehouse)


def test_the_expense_account_is_remembered_by_service_and_supplier(shop, conn):
    """Bought before (all to 26, by cost item):
      03-05 supplier  «Printerin təmiri»  [Təmir]
      03-06 supplier  «İnternet»          [Rabitə]
      03-07 Beta      «printerin TƏMİRİ»  [Xidmət]
    The same service from the same supplier wins over a later one from Beta; from anyone,
    the latest one; a service never bought takes the supplier's last service. A draft
    teaches nothing: only posted purchases count."""
    from modern_gl.application.queries import remembered_expense

    repair, telecom, service = values(shop, "cost_item", "Təmir", "Rabitə", "Xidmət")
    beta = shop.ledger.add_subconto_value(
        shop.company_id, shop.ledger.subconto_kind_id(shop.company_id, "counterparty"), "Beta"
    )

    def buy(date: str, party: list[int], memo: str, value: int) -> None:
        line = ReceiptLine(
            None,
            None,
            None,
            "10",
            memo,
            expense_account_id=shop.acc["26"],
            expense_subconto=[value],
        )
        shop.inventory.post_receipt(shop.company_id, date, [line], shop.acc["60"], party)

    buy("2026-03-05", shop.supplier, "Printerin təmiri", repair)
    buy("2026-03-06", shop.supplier, "İnternet", telecom)
    buy("2026-03-07", [beta], "printerin TƏMİRİ", service)
    cid, supplier, cost = shop.company_id, shop.supplier[0], shop.acc["26"]
    assert remembered_expense(conn, cid, "Printerin təmiri", supplier) == (
        cost,
        (repair, None, None),
    )
    assert remembered_expense(conn, cid, "Printerin təmiri", beta) == (cost, (service, None, None))
    assert remembered_expense(conn, cid, "printerin temiri") == (cost, (service, None, None))
    assert remembered_expense(conn, cid, "Kartric", supplier) == (cost, (telecom, None, None))
    assert remembered_expense(conn, cid, "Kartric", beta) == (cost, (service, None, None))
    assert remembered_expense(conn, cid, "Kartric") is None
    shop.inventory.create_receipt_draft(
        cid,
        "2026-03-08",
        [ReceiptLine(None, None, None, "5", "Kartric", expense_account_id=shop.acc["08"])],
        shop.acc["60"],
        shop.supplier,
    )
    assert remembered_expense(conn, cid, "Kartric", supplier) == (cost, (telecom, None, None))


def test_receipt_page_fills_the_expense_account_of_a_service_bought_before(shop, conn, qtbot):
    """«Printerin təmiri» was bought to 26 [Təmir]: typed again, the line takes 26 [Təmir]
    and posts Dt 26 / Kt 60 30.00 + VAT 5.40. A new service gets nothing until its supplier
    is chosen, then the supplier's last account; one typed by hand is not replaced."""
    (repair,) = values(shop, "cost_item", "Təmir")
    purchase(
        shop,
        [
            ReceiptLine(
                None,
                None,
                None,
                "50",
                "Printerin təmiri",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            )
        ],
    )
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model

    page._make_service(0, "printerin təmiri")
    assert (model.rows[0].expense_account_id, model.rows[0].expense_subconto) == (
        shop.acc["26"],
        [repair, None, None],
    )

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    put(0, AMOUNT, 3_000)
    put(0, SC1, shop.supplier[0])
    put(0, SC2, shop.supplier[1])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("26", "60", 3_000), ("19", "60", 540)]

    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    page._make_service(0, "Kartric")
    assert model.rows[0].expense_account_id is None  # no cartridge was bought yet
    put(0, SC1, shop.supplier[0])
    assert model.rows[0].expense_account_id == shop.acc["26"]  # the supplier's last service
    put(0, EXPENSE, shop.acc["08"])
    put(0, SC1, None)
    put(0, SC1, shop.supplier[0])
    assert model.rows[0].expense_account_id == shop.acc["08"]
