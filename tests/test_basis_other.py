"""The basis «Digər» (D217): a purchase or a sale on an act, a receipt… named in
free text. The text stays on the document: no number on the postings, so the portal
reconciliation, the ƏDV and «Ждёт e-qaimə» do not see it. Numbers by hand in docstrings."""

from __future__ import annotations

import pytest

from modern_gl.application.inventory import ReceiptLine
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.trade import awaiting_invoices, trade_documents
from tests.helpers.sales import Shop, make_shop, two_lines


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def purchase(shop: Shop, note: str, **kwargs) -> int:
    """10 printers for 100.00 on «Digər», saved as a draft."""
    return shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-02",
        [ReceiptLine(shop.item, shop.main, "10", "100", **kwargs)],
        shop.acc["60"],
        shop.supplier,
        basis_note=note,
    )


def test_a_purchase_on_another_document_keeps_its_name_off_the_postings(shop):
    """Dt 41 / Kt 60 100.00 — without a number; the act's name is on the document."""
    document_id = purchase(shop, "  Akt   №5, 03.11 ")
    shop.inventory.post_document(shop.company_id, document_id)

    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.basis_note, doc.invoice, doc.awaits_invoice) == ("Akt №5, 03.11", "", False)
    assert [
        (dt, kt, amount, invoice) for dt, kt, amount, _, invoice in shop.postings(document_id)
    ] == [("41", "60", 10000, None)]
    (row,) = trade_documents(shop.ledger.conn, shop.company_id, "receipt")
    assert (row.invoice, row.basis_note) == ("", "Akt №5, 03.11")
    assert awaiting_invoices(shop.ledger.conn, shop.company_id, "2026-12-31") == []


def test_a_purchase_on_another_document_takes_no_vat(shop):
    """ƏDV 18.00 of 100.00 cannot be taken without an e-qaimə: the draft is refused."""
    with pytest.raises(ValidationError, match="Digər"):
        purchase(shop, "Akt №5", vat_amount="18")
    assert trade_documents(shop.ledger.conn, shop.company_id, "receipt") == []


def test_a_document_has_one_basis(shop):
    with pytest.raises(ValidationError, match="одно основание"):
        shop.inventory.create_receipt_draft(
            shop.company_id,
            "2026-03-02",
            [ReceiptLine(shop.item, shop.main, "10", "100")],
            shop.acc["60"],
            shop.supplier,
            invoice="MT1",
            basis_note="Akt №5",
        )
    with pytest.raises(ValidationError, match="одно основание"):
        shop.inventory.create_receipt_draft(
            shop.company_id,
            "2026-03-02",
            [ReceiptLine(shop.item, shop.main, "10", "100")],
            shop.acc["60"],
            shop.supplier,
            awaits_invoice=True,
            basis_note="Akt №5",
        )


def test_a_sale_on_another_document_still_charges_vat(shop):
    """The ƏDV of a sale is owed with or without an e-qaimə: 46 / 68.2 15.30 (10.80 +
    4.50), the customer owes 70.80 + 29.50 = 100.30; no posting has a number."""
    shop.receipt("2026-01-10", "10", "200")
    document_id = shop.inventory.create_sale_draft(
        shop.company_id,
        "2026-01-20",
        two_lines(shop),
        shop.acc["62"],
        [shop.customer, shop.contract],
        "Продажа",
        vat_rate=1800,
        basis_note="Qəbz №12",
    )
    shop.inventory.post_document(shop.company_id, document_id)

    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.basis_note, doc.invoice) == ("Qəbz №12", "")
    postings = shop.postings(document_id)
    assert {invoice for *_, invoice in postings} == {None}
    assert [(dt, kt, amount) for dt, kt, amount, *_ in postings if kt == "68.2"] == [
        ("46", "68.2", 1530)
    ]
    assert sum(amount for dt, _, amount, *_ in postings if dt == "62") == 10030


def test_a_number_replaces_another_document(shop):
    """Choosing an e-qaimə again: the act's name goes, the number comes."""
    document_id = purchase(shop, "Akt №5")
    doc = shop.inventory.load_document(shop.company_id, document_id)
    shop.inventory.update_receipt_draft(
        shop.company_id,
        document_id,
        doc.doc_date,
        [ReceiptLine(shop.item, shop.main, "10", "100", line_id=doc.lines[0].id)],
        shop.acc["60"],
        shop.supplier,
        invoice="mt 7",
    )
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.basis_note, doc.invoice) == ("", "MT7")


def page_of(shop: Shop, conn, qtbot, doc_type: str):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import theme
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session
    from tests.helpers.qt import running_app

    theme.apply(running_app())
    s = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        notify=lambda _m: None,
    )
    page = InventoryDocumentPage(s, doc_type=doc_type)
    qtbot.addWidget(page)
    return page, s


def choose(page, data: str) -> None:
    page.basis.setCurrentIndex(page.basis.findData(data))
    page.basis.activated.emit(page.basis.currentIndex())


def test_purchase_form_takes_another_document(shop, conn, qtbot):
    """«Digər» in the basis box: the VAT rate goes to «без ƏDV», the field takes the act's
    name; saved, the list of purchases shows it."""
    from modern_gl.desktop.inventory_document_page.form import OTHER
    from modern_gl.desktop.trade_page import TradePage
    from tests.helpers.entry_keys import type_text

    draft = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-05",
        [ReceiptLine(shop.item, shop.main, "1", "10")],
        shop.acc["60"],
        shop.supplier,
        vat_rate=1800,
    )
    page, s = page_of(shop, conn, qtbot, "receipt")
    page.load(draft)
    assert page._chosen_vat_rate() == 1800
    choose(page, OTHER)
    assert page._chosen_vat_rate() is None
    page.invoice.clear()
    type_text(page.invoice, "Akt №5")
    assert page.save(post=True)
    doc = shop.inventory.load_document(shop.company_id, draft)
    assert (doc.status, doc.invoice, doc.basis_note, doc.vat_rate) == (
        "posted",
        "",
        "Akt №5",
        None,
    )
    assert page.basis.currentData() == OTHER and page.invoice.text() == "Akt №5"

    trade = TradePage(s, "receipt")
    qtbot.addWidget(trade)
    assert trade._invoice(trade.model.rows[0]) == "Akt №5"


def test_sale_form_offers_an_e_qaime_or_another_document(shop, conn, qtbot):
    from modern_gl.desktop.inventory_document_page.form import OTHER
    from modern_gl.domain.invoice import EQAIME

    page, _ = page_of(shop, conn, qtbot, "sale")
    page._set_new()
    items = [page.basis.itemData(i) for i in range(page.basis.count())]
    assert items == [EQAIME, OTHER]
    assert not page.basis.isHidden() and page.invoice_caption.isHidden()
    choose(page, OTHER)
    page.invoice.setText("Qəbz №12")
    assert page._invoice() == {"invoice": "", "basis_note": "Qəbz №12"}
