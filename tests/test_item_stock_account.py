"""The stock account of an item that already has documents (D202): the
goods were put on 10 «Материалы» by the default of the item's window, the books need 41 —
the account changes at the item and its documents are posted again, on the new account.
Every figure is worked out by hand in the test's docstring."""

from __future__ import annotations

import pytest

from modern_gl.application.inventory import ReceiptLine, SaleLine
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def turnover(conn, account_id: int) -> tuple[int, int]:
    """(debit, credit) of the account over all postings."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN debit_account_id = :a THEN amount END), 0) AS dt, "
        "COALESCE(SUM(CASE WHEN credit_account_id = :a THEN amount END), 0) AS ct "
        "FROM postings WHERE :a IN (debit_account_id, credit_account_id)",
        {"a": account_id},
    ).fetchone()
    return row["dt"], row["ct"]


def scanner_bought_and_sold(shop: Shop, conn) -> tuple[int, int, list[int]]:
    """«Skaner» on 10: bought 2 for 200.00 on 01.03, 1 sold on 05.03 for 150.00 + 27.00.
    Its cost is 200.00 / 2 = 100.00 a piece. (item, unit, the GL documents)."""
    cid = shop.company_id
    unit = conn.execute(
        "SELECT unit_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    scanner = shop.inventory.add_item(cid, "Skaner", unit, shop.acc["10"])
    receipt = shop.inventory.post_receipt(
        cid,
        "2026-03-01",
        [ReceiptLine(scanner, shop.main, "2", "200")],
        shop.acc["60"],
        shop.supplier,
    )
    sale = shop.sale("2026-03-05", [SaleLine(scanner, shop.main, "1", "150", "27")])
    gl = [shop.inventory.load_document(cid, d).gl_document_id for d in (receipt, sale)]
    return scanner, unit, [g for g in gl if g is not None]


def test_the_stock_account_of_an_item_with_documents_moves_its_postings(shop, conn):
    """On 10: Dt 200.00 (the purchase), Kt 100.00 (the cost of the one sold), 100.00 left.
    The account changed to 41: 10 has no turnover, 41 has Dt 200.00, Kt 100.00; the GL
    documents are the same ones, the stock is still 1 piece (1 000 000 millionths)
    for 100.00."""
    cid = shop.company_id
    scanner, unit, gl_before = scanner_bought_and_sold(shop, conn)
    assert turnover(conn, shop.acc["10"]) == (20_000, 10_000)
    assert turnover(conn, shop.acc["41"]) == (0, 0)

    shop.inventory.update_item(cid, scanner, unit, shop.acc["41"])

    assert turnover(conn, shop.acc["10"]) == (0, 0)
    assert turnover(conn, shop.acc["41"]) == (20_000, 10_000)
    documents = conn.execute(
        "SELECT gl_document_id, status FROM inventory_documents WHERE company_id = ? "
        "AND gl_document_id IS NOT NULL ORDER BY id",
        (cid,),
    ).fetchall()
    assert [d["gl_document_id"] for d in documents] == gl_before
    assert {d["status"] for d in documents} == {"posted"}
    assert [(b.item_name, b.quantity, b.amount) for b in stock_balances(conn, cid)] == [
        ("Skaner", 1_000_000, 10_000)
    ]


def test_documents_in_the_closed_period_keep_the_stock_account(shop, conn):
    """March is closed: its postings may not move, so the account stays 10."""
    cid = shop.company_id
    scanner, unit, _gl = scanner_bought_and_sold(shop, conn)
    shop.ledger.set_closed_through(cid, "2026-03-31")
    with pytest.raises(ValidationError, match="закрытом периоде"):
        shop.inventory.update_item(cid, scanner, unit, shop.acc["41"])
    assert turnover(conn, shop.acc["10"]) == (20_000, 10_000)
    row = conn.execute(
        "SELECT inventory_account_id FROM inventory_items WHERE id = ?", (scanner,)
    ).fetchone()
    assert row["inventory_account_id"] == shop.acc["10"]


def test_the_unit_of_an_item_with_documents_stays(shop, conn):
    """The quantities of its documents are in the unit: only the account may change."""
    cid = shop.company_id
    scanner, _unit, _gl = scanner_bought_and_sold(shop, conn)
    metre = shop.inventory.add_unit(cid, "m", "Metr", precision=2)
    with pytest.raises(ValidationError, match="единицу товара менять нельзя"):
        shop.inventory.update_item(cid, scanner, metre, shop.acc["41"])
    assert turnover(conn, shop.acc["41"]) == (0, 0)


# ---- the purchase page: the account is seen and changed on the line ---------------------


def purchase_page(shop: Shop, conn, qtbot, document_id: int | None = None):
    from datetime import date

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session

    notes: list[str] = []
    session = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        notify=notes.append,
        working_date=date(2026, 3, 5),
    )
    page = InventoryDocumentPage(session, document_id, doc_type="receipt")
    qtbot.addWidget(page)
    page.show()
    page.notes = notes  # pyright: ignore[reportAttributeAccessIssue]
    return page


def test_a_purchase_line_shows_the_stock_account_and_changes_it(shop, conn, qtbot):
    """The purchase of «Skaner» (2 for 200.00, on 10) is opened: «Счёт» of its line says
    «10 Материалы» and offers the stock accounts only. 41 picked there: the item is on 41,
    and so are its postings — 10 is empty, 41 has Dt 200.00, Kt 100.00 (the one sold)."""
    from modern_gl.desktop.inventory_document_page.columns import EXPENSE

    cid = shop.company_id
    _scanner, _unit, _gl = scanner_bought_and_sold(shop, conn)
    receipt = conn.execute(
        "SELECT id FROM inventory_documents WHERE company_id = ? AND doc_type = 'receipt'", (cid,)
    ).fetchone()["id"]
    page = purchase_page(shop, conn, qtbot, receipt)
    model, table = page.model, page.table
    column = model.columns.index(EXPENSE)
    assert not table.isColumnHidden(column)
    cell = model.index(0, column)
    assert str(model.data(cell)).startswith("10")
    offered = {account_id for account_id, _label in model.choices(0, EXPENSE)}
    assert offered == {shop.acc[code] for code in ("10", "40", "41")}  # not 44, not 60

    assert model.setData(cell, shop.acc["41"])

    assert str(model.data(cell)).startswith("41")
    assert turnover(conn, shop.acc["10"]) == (0, 0)
    assert turnover(conn, shop.acc["41"]) == (20_000, 10_000)
    assert page.notes[-1].startswith("«Skaner»: счёт запасов — 41")  # pyright: ignore[reportAttributeAccessIssue]
    assert not page.is_dirty()  # the item changed, not the document


def test_goods_do_not_go_to_an_expense_account(shop, conn, qtbot):
    from modern_gl.desktop.inventory_document_page.columns import EXPENSE

    cid = shop.company_id
    scanner_bought_and_sold(shop, conn)
    receipt = conn.execute(
        "SELECT id FROM inventory_documents WHERE company_id = ? AND doc_type = 'receipt'", (cid,)
    ).fetchone()["id"]
    page = purchase_page(shop, conn, qtbot, receipt)
    cell = page.model.index(0, page.model.columns.index(EXPENSE))
    with pytest.raises(ValidationError, match="не счёт запасов"):
        page.model.setData(cell, shop.acc["44"])
    assert turnover(conn, shop.acc["10"]) == (20_000, 10_000)


def test_enter_passes_by_the_stock_account_of_a_goods_line(shop, conn, qtbot):
    """The account is the item's, set once: Enter and Tab do not stop in it."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView

    from modern_gl.desktop.inventory_document_page.columns import EXPENSE

    cid = shop.company_id
    scanner_bought_and_sold(shop, conn)
    receipt = conn.execute(
        "SELECT id FROM inventory_documents WHERE company_id = ? AND doc_type = 'receipt'", (cid,)
    ).fetchone()["id"]
    page = purchase_page(shop, conn, qtbot, receipt)
    model, table = page.model, page.table
    column = model.columns.index(EXPENSE)
    before = max(
        c
        for c in range(column)
        if not table.isColumnHidden(c)
        and model.flags(model.index(0, c)) & Qt.ItemFlag.ItemIsEnabled
    )
    table.setCurrentIndex(model.index(0, before))
    moved = table.moveCursor(
        QAbstractItemView.CursorAction.MoveNext, Qt.KeyboardModifier.NoModifier
    )
    assert moved.isValid() and (moved.row(), moved.column()) != (0, column)
    assert model.flags(model.index(0, column)) & Qt.ItemFlag.ItemIsEditable  # the mouse may


def test_a_new_item_starts_on_the_account_of_the_item_before(shop, conn, qtbot):
    """The first item of a company starts on the first stock account (10); «Printer» is
    on 41, so the next one starts on 41 — in the item's window and in «Строки — товары»."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.application.inventory import Inventory
    from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
    from modern_gl.desktop.inventory_page.dialogs import ItemDialog
    from modern_gl.desktop.session import Session

    cid = shop.company_id
    session = Session(conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid))
    dialog = ItemDialog(session, Inventory(conn, actor="test"), name="Kabel")
    qtbot.addWidget(dialog)
    assert dialog.accounts.currentData() == shop.acc["41"]
    names = NewNamesDialog(session, "", True, lines=[(0, "Kabel")], chosen={0})
    qtbot.addWidget(names)
    assert names.account.currentData() == shop.acc["41"]


def test_the_item_window_changes_the_account_of_a_used_item(shop, conn, qtbot):
    """With documents the unit is locked, the account is not: the window says what a
    change does, and saving it moves the postings (10: nothing, 41: Dt 200.00, Kt 100.00)."""
    from PySide6.QtWidgets import QLabel

    from modern_gl.application.catalog import Catalog
    from modern_gl.application.inventory import Inventory
    from modern_gl.desktop.inventory_page.dialogs import ItemDialog
    from modern_gl.desktop.session import Session
    from modern_gl.reporting.inventory import item_details

    cid = shop.company_id
    scanner, _unit, _gl = scanner_bought_and_sold(shop, conn)
    value_id = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (scanner,)
    ).fetchone()[0]
    session = Session(conn, shop.ledger, cid, "Mağaza", Catalog(conn, cid))
    details = item_details(conn, cid, value_id)
    assert details is not None and details.used
    dialog = ItemDialog(session, Inventory(conn, actor="test"), item=details)
    qtbot.addWidget(dialog)
    assert dialog.accounts.isEnabled() and not dialog.units.isEnabled()
    notes = [label.text() for label in dialog.findChildren(QLabel)]
    assert (
        "По товару есть документы: единица не меняется; со сменой счёта они проведутся заново"
        in notes
    )
    dialog.accounts.setCurrentIndex(dialog.accounts.findData(shop.acc["41"]))
    dialog._save()
    assert turnover(conn, shop.acc["10"]) == (0, 0)
    assert turnover(conn, shop.acc["41"]) == (20_000, 10_000)
