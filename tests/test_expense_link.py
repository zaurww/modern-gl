"""D220: an expense of a batch names the purchase of the goods it is for — the broker's or
the terminal's e-qaimə seldom says the declaration's number, so the accountant says it.
The link is a note: the expense waits as before, the batch finds it ticked.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QLineEdit

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import ReceiptLine
from modern_gl.desktop.inventory_document_page import AMOUNT, InventoryDocumentPage
from modern_gl.desktop.inventory_document_page.columns import EXPENSE, FOR, KIND, LANDED, SERVICE
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.landed_cost_page.waiting_expenses import WaitingExpensesDialog
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import waiting_lines
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def declaration(shop: Shop, number: str = "01269999000111", day: str = "2026-07-20") -> int:
    """Ten printers for 1 000.00 on a customs declaration."""
    return shop.inventory.post_receipt(
        shop.company_id,
        day,
        [ReceiptLine(shop.item, shop.main, "10", "1000")],
        shop.acc["60"],
        shop.supplier,
        invoice=number,
        invoice_kind="customs",
    )


def terminal(shop: Shop, lines: list[tuple[str, int | None]], post: bool = True) -> int:
    """The terminal's e-qaimə: a service line of each amount on the account where the
    expenses of a batch wait, each said to be for a purchase (or for none)."""
    receipt_lines = [
        ReceiptLine(
            None,
            None,
            None,
            amount,
            "Terminal xidməti",
            expense_account_id=shop.acc["15"],
            for_document_id=target,
        )
        for amount, target in lines
    ]
    document_id = shop.inventory.create_receipt_draft(
        shop.company_id, "2026-08-31", receipt_lines, shop.acc["60"], shop.supplier
    )
    if post:
        shop.inventory.post_document(shop.company_id, document_id)
    return document_id


def test_an_expense_remembers_the_purchase_it_is_for(shop, conn):
    """One e-qaimə of the terminal, 60.00 for each of two declarations and 60.00 for none:
    every line waits on 15 as before (180.00 in all), two of them say their purchase."""
    first = declaration(shop)
    second = declaration(shop, "01269999000222", "2026-07-31")
    invoice = terminal(shop, [("60", first), ("60", second), ("60", None)])

    loaded = shop.inventory.load_document(shop.company_id, invoice)
    assert [line.for_document_id for line in loaded.lines] == [first, second, None]
    assert sorted(p[:3] for p in shop.postings(invoice)) == [("15", "60", 6_000)] * 3
    waiting = waiting_lines(conn, shop.company_id)
    assert all(w.waits and w.left == 6_000 for w in waiting)
    assert {w.for_document_id for w in waiting} == {first, second, None}
    assert sum(w.left for w in waiting) == 18_000


def test_the_link_is_rewritten_with_the_draft(shop, conn):
    """The draft saved again with another purchase, then with none: the link follows."""
    first = declaration(shop)
    second = declaration(shop, "01269999000222", "2026-07-31")
    invoice = terminal(shop, [("60", first)], post=False)
    line = shop.inventory.load_document(shop.company_id, invoice).lines[0]

    def save(target: int | None) -> None:
        shop.inventory.update_receipt_draft(
            shop.company_id,
            invoice,
            "2026-08-31",
            [
                ReceiptLine(
                    None,
                    None,
                    None,
                    "60",
                    "Terminal xidməti",
                    line_id=line.id,
                    expense_account_id=shop.acc["15"],
                    for_document_id=target,
                )
            ],
            shop.acc["60"],
            shop.supplier,
        )

    save(second)
    assert shop.inventory.load_document(shop.company_id, invoice).lines[0].for_document_id == second
    save(None)
    assert shop.inventory.load_document(shop.company_id, invoice).lines[0].for_document_id is None
    assert conn.execute("SELECT COUNT(*) FROM inventory_expense_targets").fetchone()[0] == 0


def test_only_an_expense_is_said_to_be_for_another_purchase(shop):
    first = declaration(shop)
    with pytest.raises(ValidationError, match="расход, а не товар"):
        shop.inventory.create_receipt_draft(
            shop.company_id,
            "2026-08-31",
            [ReceiptLine(shop.item, shop.main, "1", "100", for_document_id=first)],
            shop.acc["60"],
            shop.supplier,
        )
    with pytest.raises(ValidationError, match="к другой покупке товара"):
        terminal(shop, [("60", 999_999)])


def test_an_expense_is_not_for_its_own_document(shop, conn):
    invoice = terminal(shop, [("60", None)], post=False)
    line = shop.inventory.load_document(shop.company_id, invoice).lines[0]
    with pytest.raises(ValidationError, match="к другой покупке товара"):
        shop.inventory.update_receipt_draft(
            shop.company_id,
            invoice,
            "2026-08-31",
            [
                ReceiptLine(
                    None,
                    None,
                    None,
                    "60",
                    "Terminal xidməti",
                    line_id=line.id,
                    expense_account_id=shop.acc["15"],
                    for_document_id=invoice,
                )
            ],
            shop.acc["60"],
            shop.supplier,
        )


def test_the_purchase_deleted_leaves_its_expenses_for_none(shop, conn):
    """The purchase of the goods is deleted: the terminal's 60.00 still waits, for no
    purchase — nothing stops the deletion and nothing is lost."""
    first = declaration(shop)
    invoice = terminal(shop, [("60", first)])
    shop.inventory.delete_document(shop.company_id, first)
    assert shop.inventory.load_document(shop.company_id, invoice).lines[0].for_document_id is None
    (waiting,) = waiting_lines(conn, shop.company_id)
    assert (waiting.left, waiting.for_document_id) == (6_000, None)


# ---- the purchase form ---------------------------------------------------------------


def session_of(shop: Shop, conn) -> Session:
    return Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))


def purchase_page(shop: Shop, conn, qtbot, document_id: int | None = None) -> InventoryDocumentPage:
    page = (
        InventoryDocumentPage(session_of(shop, conn), document_id=document_id)
        if document_id is not None
        else InventoryDocumentPage(session_of(shop, conn), doc_type="receipt")
    )
    qtbot.addWidget(page)
    return page


def cell(page: InventoryDocumentPage, row: int, key: str):
    return page.model.index(row, page.model.columns.index(key))


def expense_line(page: InventoryDocumentPage) -> None:
    page._make_service(0, "Terminal xidməti")
    page.model.setData(cell(page, 0, AMOUNT), 6_000)
    page.model.setData(cell(page, 0, KIND), LANDED)


def test_the_form_asks_which_purchase_an_expense_is_for(shop, conn, qtbot):
    """«К покупке» appears with an expense of a batch, lists the purchases of goods by
    number, day, declaration and supplier; saved and opened again, the choice is there."""
    first = declaration(shop)
    page = purchase_page(shop, conn, qtbot)
    column = page.model.columns.index(FOR)
    assert page.table.isColumnHidden(column)
    expense_line(page)
    assert not page.table.isColumnHidden(column)
    ((choice_id, label),) = page.model.choices(0, FOR)
    assert choice_id == first
    assert "20.07.2026" in label and "01269999000111" in label and "Təchizatçı" in label

    assert page.model.setData(cell(page, 0, FOR), first)
    assert page.model.data(cell(page, 0, FOR)) == "01269999000111"  # the cell is narrow
    page.model.set_party(shop.acc["60"], [*shop.supplier, None])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None

    again = purchase_page(shop, conn, qtbot, page.doc.id)
    assert again.model.rows[0].for_document_id == first
    assert not again.table.isColumnHidden(column)
    (waiting,) = waiting_lines(conn, shop.company_id)
    assert (waiting.left, waiting.for_document_id) == (6_000, first)


def test_the_purchase_is_found_by_what_is_typed(shop, conn, qtbot):
    """A part of the declaration's number names the purchase; a text that names none is
    told, and nothing is set."""
    first = declaration(shop)
    page = purchase_page(shop, conn, qtbot)
    expense_line(page)
    page.delegate.setModelData(QLineEdit("000111"), page.model, cell(page, 0, FOR))
    assert page.model.rows[0].for_document_id == first
    page.model.rows[0].for_document_id = None
    page.delegate.setModelData(QLineEdit("zzz"), page.model, cell(page, 0, FOR))
    assert page.model.rows[0].for_document_id is None
    assert page.error.text() == tr("покупка не найдена: {text}", text="zzz")


def test_another_kind_forgets_the_purchase(shop, conn, qtbot):
    """«Счёт» picked, or another account typed: the line is no expense of a batch and is
    for no purchase; the column goes."""
    first = declaration(shop)
    page = purchase_page(shop, conn, qtbot)
    expense_line(page)
    page.model.setData(cell(page, 0, FOR), first)
    page.model.setData(cell(page, 0, EXPENSE), shop.acc["44"])
    assert page.model.rows[0].for_document_id is None
    assert page.table.isColumnHidden(page.model.columns.index(FOR))
    page.model.setData(cell(page, 0, KIND), LANDED)
    page.model.setData(cell(page, 0, FOR), first)
    page.model.setData(cell(page, 0, KIND), SERVICE)
    assert page.model.rows[0].for_document_id is None


def test_a_split_line_keeps_the_purchase_for_each_part(shop, conn, qtbot):
    """The terminal's 60.00 split in two for two declarations: each part starts with the
    purchase of the line and is given its own."""
    first = declaration(shop)
    second = declaration(shop, "01269999000222", "2026-07-31")
    page = purchase_page(shop, conn, qtbot)
    expense_line(page)
    page.model.setData(cell(page, 0, FOR), first)
    new_row = page.model.split_row(0, amount=3_000)
    assert [row.for_document_id for row in page.model.rows] == [first, first]
    page.model.setData(cell(page, new_row, FOR), second)
    assert [(row.amount, row.for_document_id) for row in page.model.rows] == [
        (3_000, first),
        (3_000, second),
    ]


# ---- the batch -------------------------------------------------------------------------


def test_the_batch_ticks_what_was_said_to_be_for_its_purchase(shop, conn, qtbot, monkeypatch):
    """Two terminal lines of 60.00 wait, neither names a declaration in its text; the one
    said to be for the first purchase comes ticked when that purchase is chosen."""
    first = declaration(shop)
    second = declaration(shop, "01269999000222", "2026-07-31")
    terminal(shop, [("60", first), ("60", second)])
    rows = waiting_lines(conn, shop.company_id)
    dialog = WaitingExpensesDialog(rows, (), None, {first})
    qtbot.addWidget(dialog)
    assert [(row.left, row.for_document_id) for row in dialog.chosen()] == [(6_000, first)]

    monkeypatch.setattr(WaitingExpensesDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)
    page = LandedCostPage(session_of(shop, conn))
    qtbot.addWidget(page)
    page.add_waiting((), {second})
    assert [row.amount for row in page.charges.rows if row.taken] == [6_000]
