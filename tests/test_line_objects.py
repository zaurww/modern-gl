"""Many lines of one purchase at once (D172): a value picked with several lines selected
goes to all of them; each fixed asset line gets an asset of its own, named by the line.

The numbers are worked out by hand in the test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QDialog, QStyleOptionViewItem

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.cell_editing import CellEditor
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ESC1,
    EXPENSE,
    SC1,
    SC2,
    InventoryDocumentPage,
    NewNamesDialog,
)
from modern_gl.desktop.session import Session
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def kind_id(shop: Shop, code: str) -> int:
    return shop.ledger.subconto_kind_id(shop.company_id, code)


def purchase_page(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    """An e-qaimə of two air conditioners and two pieces of furniture, all to account."""
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    lines = [("Kondisioner A", 100_000), ("Kondisioner B", 120_000), ("Stul", 5_000)]
    for row, (name, amount) in enumerate([*lines, ("Masa", 8_000)]):
        if row:
            model.insert_row()
        page._make_service(row, name)
        model.setData(model.index(row, model.columns.index(AMOUNT)), amount)
    return page


def typed(page: InventoryDocumentPage, row: int, key: str, text: str) -> None:
    """The text typed into the cell and committed, as the user does."""
    model = page.model
    index = model.index(row, model.columns.index(key))
    editor = CellEditor()
    editor.setText(text)
    page.delegate.setModelData(editor, model, index)


def select(page: InventoryDocumentPage, key: str, rows: list[int]) -> None:
    model, selection = page.model, page.table.selectionModel()
    selection.clearSelection()
    for row in rows:
        index = model.index(row, model.columns.index(key))
        selection.select(index, QItemSelectionModel.SelectionFlag.Select)
    current = model.index(rows[0], model.columns.index(key))
    selection.setCurrentIndex(current, QItemSelectionModel.SelectionFlag.NoUpdate)


def test_lines_selected_take_one_value_and_assets_are_named_by_their_lines(
    shop, conn, qtbot, monkeypatch
):
    """08 on the first line goes to all four (none has an account). The furniture lines
    selected take 26 and «Ofis» at once. «Kondisioner A» is in the directory already:
    the first line takes it, the second gets a new asset «Kondisioner B».
    Posted: Dt 08 1 000.00 [Kondisioner A] and 1 200.00 [Kondisioner B]; Dt 26 [Ofis]
    50.00 and 80.00; VAT 18%: 180.00 + 216.00 + 9.00 + 14.40 = 419.40 — all Kt 60."""
    known = shop.ledger.add_subconto_value(
        shop.company_id, kind_id(shop, "fixed_asset"), "Kondisioner A"
    )
    office = shop.ledger.add_subconto_value(shop.company_id, kind_id(shop, "cost_item"), "Ofis")
    page = purchase_page(shop, conn, qtbot)
    model = page.model

    typed(page, 0, EXPENSE, "08")
    assert {row.expense_account_id for row in model.rows} == {shop.acc["08"]}
    select(page, EXPENSE, [2, 3])
    typed(page, 2, EXPENSE, "26")
    assert [row.expense_account_id for row in model.rows] == [shop.acc["08"]] * 2 + [
        shop.acc["26"]
    ] * 2
    select(page, ESC1, [2, 3])
    typed(page, 2, ESC1, "Ofis")
    assert [row.expense_subconto[0] for row in model.rows] == [None, None, office, office]

    # an empty asset cell opens with the line's name: Enter makes it
    index = model.index(1, model.columns.index(ESC1))
    editor = page.delegate.createEditor(page.table.viewport(), QStyleOptionViewItem(), index)
    page.delegate.setEditorData(editor, index)
    assert editor.text() == "Kondisioner B"

    assert page.btn_objects.isVisibleTo(page)
    asked = []

    def accept(dialog: NewNamesDialog):
        asked.append(dialog.checked_rows())
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NewNamesDialog, "exec", accept)
    page._make_objects()
    assert asked == [[0, 1]]
    second = page.s.catalog.resolve_value(kind_id(shop, "fixed_asset"), "Kondisioner B")
    assert second is not None and second != known
    assert [row.expense_subconto[0] for row in model.rows] == [known, second, office, office]
    assert not page.btn_objects.isVisibleTo(page)

    for row in range(4):
        model.setData(model.index(row, model.columns.index(SC1)), shop.supplier[0])
        model.setData(model.index(row, model.columns.index(SC2)), shop.supplier[1])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert sorted(p[:3] for p in shop.postings(page.doc.id)) == sorted(
        [
            ("08", "60", 100_000),
            ("08", "60", 120_000),
            ("26", "60", 5_000),
            ("26", "60", 8_000),
            ("19", "60", 41_940),
        ]
    )


def test_assets_named_alike_are_one_and_made_in_one_go(shop):
    """«Ofis stolu» twice and «ofis STOLU» are one element; «Printer» is new."""
    kind = kind_id(shop, "fixed_asset")
    ids = shop.ledger.add_named_values(
        shop.company_id, kind, ["Ofis stolu", "Printer", "ofis STOLU"]
    )
    assert ids[0] == ids[2] and ids[0] != ids[1]
