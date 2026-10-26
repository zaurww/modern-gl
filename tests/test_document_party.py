"""The supplier of a purchase, the customer of a sale — chosen once in the header: every
line takes it, the account and subconto columns are not shown; lines with different ones
show theirs."""

from __future__ import annotations

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import ReceiptLine
from modern_gl.desktop.inventory_document_page import (
    ACCOUNT,
    AMOUNT,
    ITEM,
    QUANTITY,
    SC1,
    WAREHOUSE,
    InventoryDocumentPage,
)
from modern_gl.desktop.session import Session
from tests.test_sales import Shop, make_shop


def page_of(shop: Shop, conn, qtbot, document_id=None, doc_type="receipt"):
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, document_id, doc_type=doc_type)
    qtbot.addWidget(page)
    page.show()
    return page


def shown(page: InventoryDocumentPage, key: str) -> bool:
    return not page.table.isColumnHidden(page.model.columns.index(key))


def test_the_supplier_in_the_header_goes_to_every_line(conn, qtbot):
    """2 printers for 30.00 from «Təchizatçı» under «Tədarük»: chosen in the header, not
    in the line; posted Dt 41 / Kt 60 [Təchizatçı, Tədarük] 30.00 + VAT 5.40."""
    shop = make_shop(conn, "classic")
    page = page_of(shop, conn, qtbot)
    assert page.party.isVisibleTo(page) and page.party_caption.text() == "Поставщик"
    assert not shown(page, ACCOUNT) and not shown(page, SC1)
    supplier, contract = shop.supplier
    page.party.setCurrentIndex(page.party.findData(supplier))
    page._party_chosen()
    page.contract.setCurrentIndex(page.contract.findData(contract))
    page._party_chosen(keep_contract=True)
    model = page.model
    for key, value in (
        (ITEM, shop.item),
        (WAREHOUSE, shop.main),
        (QUANTITY, 2_000_000),
        (AMOUNT, 3_000),
    ):
        model.setData(model.index(0, model.columns.index(key)), value)
    model.insert_row()  # a new line takes the header's supplier too
    assert model.rows[1].offset_subconto == model.rows[0].offset_subconto
    assert page.save(post=True), page.error.text()
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("41", "60", 3_000), ("19", "60", 540)]
    line = conn.execute(
        "SELECT dt_sc1, ct_sc1, ct_sc2 FROM postings WHERE document_id = ? AND line_no = 1",
        (page.doc.gl_document_id,),
    ).fetchone()
    assert (line["ct_sc1"], line["ct_sc2"]) == (supplier, contract)


def test_lines_with_different_suppliers_show_theirs(conn, qtbot):
    """A purchase whose two lines came from two suppliers: the header is empty, the
    columns are shown. Choosing one in the header gives it to both lines."""
    shop = make_shop(conn, "classic")
    other = shop.ledger.add_subconto_value(
        shop.company_id, shop.ledger.subconto_kind_id(shop.company_id, "counterparty"), "Beta"
    )
    document_id = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-01-10",
        [
            ReceiptLine(
                shop.item,
                shop.main,
                "1",
                "10",
                credit_account_id=shop.acc["60"],
                credit_subconto=shop.supplier,
            ),
            ReceiptLine(
                shop.item,
                shop.main,
                "1",
                "12",
                credit_account_id=shop.acc["60"],
                credit_subconto=[other],
            ),
        ],
        shop.acc["60"],
        shop.supplier,
    )
    page = page_of(shop, conn, qtbot, document_id)
    assert page.model.by_lines and shown(page, ACCOUNT) and shown(page, SC1)
    assert page.party.currentData() is None
    page.party.setCurrentIndex(page.party.findData(other))
    page._party_chosen()
    assert [r.offset_subconto[0] for r in page.model.rows] == [other, other]
    assert not shown(page, ACCOUNT)


def test_a_sale_names_its_customer(conn, qtbot):
    shop = make_shop(conn, "classic")
    page = page_of(shop, conn, qtbot, doc_type="sale")
    assert page.party_caption.text() == "Покупатель"
    assert page.party.findData(shop.customer) >= 0
