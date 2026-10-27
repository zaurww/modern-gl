"""An account chosen on one service line of a purchase goes to the others without one.

The numbers are worked out by hand in the test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.catalog import Catalog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ESC1,
    EXPENSE,
    SC1,
    SC2,
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def values(shop: Shop, kind: str, *names: str) -> list[int]:
    kind_id = shop.ledger.subconto_kind_id(shop.company_id, kind)
    return [shop.ledger.add_subconto_value(shop.company_id, kind_id, name) for name in names]


def test_an_air_conditioner_and_its_installation_go_to_one_fixed_asset(shop, conn, qtbot):
    """An e-qaimə: «Komplekt montaj» 100.00, the air conditioner 2 340.68, «Kartric»
    30.00. 08 on the first line goes to the two others; the third changed to 26 changes
    no other line; the asset «Kondisioner» chosen on the second stays its own (each line
    has its own asset), the first is given it by hand.
    Posted: Dt 08 [Kondisioner] / Kt 60 100.00 + 2 340.68 = 2 440.68; Dt 26 / Kt 60 30.00;
    VAT 18%: 18.00 + 421.32 (2 340.68 × 0.18 = 421.3224) + 5.40 = 444.72."""
    (conditioner,) = values(shop, "fixed_asset", "Kondisioner")
    (office,) = values(shop, "cost_item", "Ofis")
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    model = page.model

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    for row, (name, amount) in enumerate(
        [("Komplekt montaj", 10_000), ("ASF-H60A5", 234_068), ("Kartric", 3_000)]
    ):
        if row:
            model.insert_row()
        page._make_service(row, name)
        put(row, AMOUNT, amount)

    put(0, EXPENSE, shop.acc["08"])
    assert {r.expense_account_id for r in model.rows} == {shop.acc["08"]}
    kind = shop.ledger.subconto_kind_id(shop.company_id, "fixed_asset")
    header = model.headerData(model.columns.index(ESC1), Qt.Orientation.Horizontal)
    assert header == session.catalog.kinds[kind]  # named by its directory
    put(2, EXPENSE, shop.acc["26"])
    assert [r.expense_account_id for r in model.rows] == [
        shop.acc["08"],
        shop.acc["08"],
        shop.acc["26"],
    ]
    put(1, ESC1, conditioner)
    assert [r.expense_subconto[0] for r in model.rows] == [None, conditioner, None]
    put(0, ESC1, conditioner)
    header = model.headerData(model.columns.index(ESC1), Qt.Orientation.Horizontal)
    assert header == "Субконто"  # 08 and 26 lines: two directories
    put(2, ESC1, office)
    assert [r.expense_subconto[0] for r in model.rows] == [conditioner, conditioner, office]

    for row in range(3):
        put(row, SC1, shop.supplier[0])
        put(row, SC2, shop.supplier[1])
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    postings = [p[:3] for p in shop.postings(page.doc.id)]
    assert sorted(postings) == sorted(
        [
            ("08", "60", 10_000),
            ("08", "60", 234_068),
            ("26", "60", 3_000),
            ("19", "60", 44_472),  # VAT of the document in one posting
        ]
    )
