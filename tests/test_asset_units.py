"""One line of an e-qaimə — several fixed assets (D232): 3 coffee machines for 1 000.00
on one line become three lines of one machine each, every one an asset of its own.

By hand: 1 000.00 / 3 = 333.33, 333.33 and 333.34 (the odd kopeck in the last);
VAT 18% of 1 000.00 = 180.00 → 60.00 each. Posted: Dt 01 [Qəhvə aparatı №1] 333.33,
[№2] 333.33, [№3] 333.34 — a quantity of 1 each; Dt 19 180.00; all Kt 60."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ESC1,
    EXPENSE,
    QUANTITY,
    SC1,
    SC2,
    InventoryDocumentPage,
    NewNamesDialog,
    splits,
)
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from tests.helpers.sales import Shop, make_shop

PIECE = 1_000_000  # a quantity of one, in millionths


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def machines(shop: Shop, conn, qtbot, quantity: int = 3 * PIECE) -> InventoryDocumentPage:
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model
    page._make_service(0, "Qəhvə aparatı")
    for key, value in ((EXPENSE, shop.acc["01"]), (QUANTITY, quantity), (AMOUNT, 100_000)):
        assert model.setData(model.index(0, model.columns.index(key)), value)
    page.table.setCurrentIndex(model.index(0, model.columns.index(AMOUNT)))
    return page


def test_a_line_of_three_assets_becomes_three_lines_and_three_assets(
    shop, conn, qtbot, monkeypatch
):
    page = machines(shop, conn, qtbot)
    model = page.model

    def by_unit(dialog: splits.SplitLineDialog):
        assert not dialog.btn_units.isHidden() and "3" in dialog.btn_units.text()
        dialog.btn_units.click()
        return dialog.result()

    monkeypatch.setattr(splits.SplitLineDialog, "exec", by_unit)
    monkeypatch.setattr(NewNamesDialog, "exec", lambda dialog: QDialog.DialogCode.Accepted)
    page._split_row()  # F8 → «По одной штуке»: the lines, then their assets by their names
    assert [(r.memo, r.quantity, r.amount, r.vat_amount) for r in model.rows] == [
        ("Qəhvə aparatı №1", PIECE, 33_333, 6_000),
        ("Qəhvə aparatı №2", PIECE, 33_333, 6_000),
        ("Qəhvə aparatı №3", PIECE, 33_334, 6_000),
    ]
    assets = [r.expense_subconto[0] for r in model.rows]
    assert None not in assets and len(set(assets)) == 3
    for row in range(3):
        model.setData(model.index(row, model.columns.index(SC1)), shop.supplier[0])
        model.setData(model.index(row, model.columns.index(SC2)), shop.supplier[1])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert sorted(p[:3] for p in shop.postings(page.doc.id)) == [
        ("01", "60", 33_333),
        ("01", "60", 33_333),
        ("01", "60", 33_334),
        ("19", "60", 18_000),
    ]
    gl = shop.inventory.load_document(shop.company_id, page.doc.id).gl_document_id
    on_01 = conn.execute(
        "SELECT v.name, p.quantity FROM postings p JOIN subconto_values v ON v.id = p.dt_sc1 "
        "WHERE p.document_id = ? AND p.debit_account_id = ? ORDER BY p.line_no",
        (gl, shop.acc["01"]),
    ).fetchall()
    assert [tuple(r) for r in on_01] == [
        ("Qəhvə aparatı №1", PIECE),
        ("Qəhvə aparatı №2", PIECE),
        ("Qəhvə aparatı №3", PIECE),
    ]


def test_units_are_offered_only_for_whole_objects(shop, conn, qtbot):
    """2.5 of something is not objects; an asset chosen for the lot stays on the first
    line only — the others wait for theirs; an expense (26) is not an object."""
    page = machines(shop, conn, qtbot, quantity=2_500_000)
    assert page.model.units_of(0) is None
    with pytest.raises(ValidationError):
        page.model.split_by_units(0)

    page = machines(shop, conn, qtbot, quantity=2 * PIECE)
    kind = shop.ledger.subconto_kind_id(shop.company_id, "fixed_asset")
    lot = shop.ledger.add_subconto_value(shop.company_id, kind, "Aparatlar")
    page.s.catalog.reload()
    model = page.model
    model.setData(model.index(0, model.columns.index(ESC1)), lot)
    assert model.units_of(0) == 2
    assert model.split_by_units(0) == [0, 1]
    assert [r.expense_subconto[0] for r in model.rows] == [lot, None]

    model.setData(model.index(0, model.columns.index(EXPENSE)), shop.acc["26"])
    model.setData(model.index(0, model.columns.index(QUANTITY)), 4 * PIECE)
    assert model.units_of(0) is None
