"""«Разделить строку» (D-new1): a line of a warehouse document in two, by a quantity of the
goods or an amount of the service, VAT and the currency amount following in proportion; the
parts add up to the line as it was. Every number is worked out by hand."""

from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ITEM,
    QUANTITY,
    VAT,
    InventoryDocumentPage,
)
from modern_gl.desktop.inventory_document_page.lines_split import portion, shares
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from tests.test_sales import Shop, make_shop

PIECE = 1_000_000  # a quantity of one, in millionths


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def page_of(shop: Shop, conn, qtbot) -> InventoryDocumentPage:
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    return page


def test_shares_and_portions_are_exact():
    """300.01 over three months: 100.00, 100.00, 100.01; a third of 100.01 is 33.34
    (33.336… rounds up), nothing stays None but None."""
    assert shares(30_001, 3) == [10_000, 10_000, 10_001]
    assert shares(None, 2) == [None, None]
    assert portion(10_001, 1, 3) == 3_334
    assert portion(10_000, 2, 5) == 4_000
    assert portion(None, 1, 2) is None


def test_goods_are_split_by_quantity(shop, conn, qtbot):
    """5 printers for 100.00 + ƏDV 18.00: 2 go to a new line — 40.00 + 7.20, 3 stay —
    60.00 + 10.80. The totals are what they were; the new line is a new line (no id)."""
    page = page_of(shop, conn, qtbot)
    model = page.model
    for key, value in ((ITEM, shop.item), (QUANTITY, 5 * PIECE), (AMOUNT, 10_000)):
        assert model.setData(model.index(0, model.columns.index(key)), value)
    assert model.rows[0].vat_amount == 1_800
    model.rows[0].line_id = 7  # as a saved line would have
    new_row = model.split_row(0, quantity=2 * PIECE)
    assert new_row == 1
    first, second = model.rows
    assert (first.quantity, first.amount, first.vat_amount) == (3 * PIECE, 6_000, 1_080)
    assert (second.quantity, second.amount, second.vat_amount) == (2 * PIECE, 4_000, 720)
    assert (first.line_id, second.line_id, second.item_id) == (7, None, shop.item)
    assert model.total() == 10_000 and model.vat_total() == 1_800
    with pytest.raises(ValidationError, match="больше нуля и меньше всего"):
        model.split_row(0, quantity=3 * PIECE)
    with pytest.raises(ValidationError, match="больше нуля и меньше всего"):
        model.split_row(0, quantity=0)


def test_an_odd_kopeck_stays_in_the_first_line(shop, conn, qtbot):
    """3 pieces for 100.01: one piece to the new line is 33.34 (a third of 100.01 rounded
    up), 66.67 stay; ƏDV 18.00 → 6.00 and 12.00."""
    page = page_of(shop, conn, qtbot)
    model = page.model
    for key, value in ((ITEM, shop.item), (QUANTITY, 3 * PIECE), (AMOUNT, 10_001)):
        assert model.setData(model.index(0, model.columns.index(key)), value)
    model.split_row(0, quantity=PIECE)
    assert [(r.amount, r.vat_amount) for r in model.rows] == [(6_667, 1_200), (3_334, 600)]


def test_a_service_is_split_by_amount(shop, conn, qtbot):
    """Rent 500.00 + ƏDV 90.00: 125.00 to the new line with ƏDV 22.50; 375.00 + 67.50 stay.
    Neither part keeps a quantity. The whole or nothing cannot be moved."""
    page = page_of(shop, conn, qtbot)
    page._make_service(0, "İcarə")
    model = page.model
    assert model.setData(model.index(0, model.columns.index(QUANTITY)), PIECE)
    assert model.setData(model.index(0, model.columns.index(AMOUNT)), 50_000)
    assert model.rows[0].vat_amount == 9_000
    model.split_row(0, amount=12_500)
    assert [(r.amount, r.vat_amount, r.quantity, r.memo) for r in model.rows] == [
        (37_500, 6_750, None, "İcarə"),
        (12_500, 2_250, None, "İcarə"),
    ]
    with pytest.raises(ValidationError, match="больше нуля и меньше всей"):
        model.split_row(0, amount=37_500)
    with pytest.raises(ValidationError, match="больше нуля и меньше всей"):
        model.split_row(0)


def test_a_typed_vat_is_split_the_same_way(shop, conn, qtbot):
    """ƏDV typed by hand (10.00 on 100.00) is divided like the amount: 2 of 5 take 4.00."""
    page = page_of(shop, conn, qtbot)
    model = page.model
    for key, value in ((ITEM, shop.item), (QUANTITY, 5 * PIECE), (AMOUNT, 10_000), (VAT, 1_000)):
        assert model.setData(model.index(0, model.columns.index(key)), value)
    model.split_row(0, quantity=2 * PIECE)
    assert [(r.amount, r.vat_amount) for r in model.rows] == [(6_000, 600), (4_000, 400)]


def test_the_page_splits_the_current_line_through_the_dialog(shop, conn, qtbot, monkeypatch):
    """F8 on 5 printers, «2» typed: the table stands on the new line. An empty line splits
    nothing."""
    from PySide6.QtWidgets import QDialog

    from modern_gl.desktop.inventory_document_page import splits

    page = page_of(shop, conn, qtbot)
    model = page.model
    page._split_row()  # an empty line: nothing happens
    assert len(model.rows) == 1
    for key, value in ((ITEM, shop.item), (QUANTITY, 5 * PIECE), (AMOUNT, 10_000)):
        assert model.setData(model.index(0, model.columns.index(key)), value)
    page.table.setCurrentIndex(model.index(0, model.columns.index(AMOUNT)))

    def typed(self) -> QDialog.DialogCode:
        self.edit.setText("2")
        self._accept()
        return (
            QDialog.DialogCode.Accepted if self.value is not None else QDialog.DialogCode.Rejected
        )

    monkeypatch.setattr(splits.SplitLineDialog, "exec", typed)
    page._split_row()
    assert [r.quantity for r in model.rows] == [3 * PIECE, 2 * PIECE]
    assert page.table.currentIndex().row() == 1

    dialog = splits.SplitLineDialog(page, None, 50_000)
    dialog.edit.setText("abc")
    dialog._accept()
    assert dialog.value is None and not dialog.error.isHidden()
    dialog.edit.setText("125")
    dialog._accept()
    assert dialog.value == 12_500
