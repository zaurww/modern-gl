"""A purchase whose goods came before their e-qaimə (D119): posted without a number,
marked «ждёт e-qaimə»; the e-qaimə of its supplier is written into it — by the import
from the portal, with its VAT when the amounts agree. Numbers by hand in docstrings."""

from __future__ import annotations

from decimal import Decimal

import pytest

from modern_gl.application.eqaime import (
    EInvoice,
    EInvoiceLine,
    import_drafts,
    plan_import,
)
from modern_gl.application.inventory import ReceiptLine
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.trade import trade_documents
from tests.helpers.sales import Shop, make_shop

SUPPLIER_TIN = "1700000001"


@pytest.fixture
def shop(conn) -> Shop:
    s = make_shop(conn, "classic")
    s.ledger.set_subconto_value_tax(s.company_id, s.supplier[0], SUPPLIER_TIN)
    kind = s.ledger.subconto_kind_id(s.company_id, "cost_item")
    s.ledger.add_subconto_value(s.company_id, kind, "Çatdırılma")
    return s


def delivery(shop: Shop, line_id: int | None = None) -> ReceiptLine:
    """A delivery 50.00 to 26 [Çatdırılma]."""
    cost_item = shop.ledger.conn.execute(
        "SELECT id FROM subconto_values WHERE company_id = ? AND name = 'Çatdırılma'",
        (shop.company_id,),
    ).fetchone()["id"]
    return ReceiptLine(
        None,
        None,
        None,
        "50",
        "Çatdırılma",
        expense_account_id=shop.acc["26"],
        expense_subconto=[cost_item],
        line_id=line_id,
    )


def waiting(shop: Shop, day: str = "2026-03-02", printers: str = "100") -> int:
    """10 printers for `printers` and a delivery 50.00 (on 26), without VAT, posted."""
    lines = [
        ReceiptLine(shop.item, shop.main, "10", printers),
        delivery(shop),
    ]
    document_id = shop.inventory.create_receipt_draft(
        shop.company_id, day, lines, shop.acc["60"], shop.supplier, awaits_invoice=True
    )
    shop.inventory.post_document(shop.company_id, document_id)
    return document_id


def einvoice(number: str, day: str, amount: int, vat: int) -> EInvoice:
    """The supplier's e-qaimə with one line of `amount` and `vat` (minor units)."""
    line = EInvoiceLine("Printer", "8443321000", "ədəd", Decimal(10), amount, vat)
    return EInvoice(
        "p-" + number,
        "avis",
        number,
        day,
        False,
        "approved",
        "defaultInvoice",
        SUPPLIER_TIN,
        "Təchizatçı MMC",
        (line,),
    )


def codes(shop: Shop, document_id: int) -> list[tuple]:
    """(Dt, Kt, amount, e-qaimə) of the purchase's postings."""
    return [(dt, kt, amount, invoice) for dt, kt, amount, _, invoice in shop.postings(document_id)]


def test_a_waiting_purchase_is_marked_and_a_number_ends_the_wait(shop):
    document_id = waiting(shop)
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.status, doc.invoice, doc.awaits_invoice) == ("posted", "", True)
    (row,) = trade_documents(shop.ledger.conn, shop.company_id, "receipt")
    assert row.awaits_invoice

    with shop.inventory.reposting(shop.company_id, document_id):
        shop.inventory.update_receipt_draft(
            shop.company_id,
            document_id,
            doc.doc_date,
            [
                ReceiptLine(shop.item, shop.main, "10", "100", line_id=doc.lines[0].id),
                delivery(shop, doc.lines[1].id),
            ],
            shop.acc["60"],
            shop.supplier,
            invoice="mt 1",
            awaits_invoice=True,  # a number wins: nothing waits any more
        )
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.invoice, doc.awaits_invoice) == ("MT1", False)


def test_only_a_purchase_waits(shop):
    document_id = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-01",
        [ReceiptLine(shop.item, shop.main, "1", "10")],
        shop.acc["60"],
        shop.supplier,
        opening=True,
        awaits_invoice=True,
    )
    assert not shop.inventory.load_document(shop.company_id, document_id).awaits_invoice


def test_import_writes_the_einvoice_and_its_vat_into_the_waiting_purchase(shop, conn):
    """Posted on 02.03 without VAT: 41/60 100.00, 26/60 50.00. The e-qaimə of 05.03 is
    150.00 + VAT 10.01 — the same amount without VAT, so its VAT is split by the lines'
    amounts, largest remainder: 10.01 × 100/150 = 6.6733, 10.01 × 50/150 = 3.3367 →
    6.67 and 3.33, the last kopek to the larger remainder (0.67 > 0.33): 6.67 + 3.34.
    Posted again in place: the number on every posting and 19/60 10.01 for the VAT;
    no new draft."""
    document_id = waiting(shop)
    assert codes(shop, document_id) == [("41", "60", 10_000, None), ("26", "60", 5_000, None)]

    (plan,) = plan_import(conn, shop.company_id, [einvoice("MT0305", "2026-03-05", 15_000, 1_001)])
    assert [p.document_id for p in plan.awaiting] == [document_id]
    assert plan.attach_to is not None and plan.attach_to.document_id == document_id

    assert import_drafts(shop.inventory, shop.company_id, [plan]) == []
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.status, doc.invoice, doc.awaits_invoice) == ("posted", "MT0305", False)
    assert [line.vat_amount for line in doc.lines] == [667, 334]
    assert doc.vat_rate == 1800
    assert codes(shop, document_id) == [
        ("41", "60", 10_000, "MT0305"),
        ("26", "60", 5_000, "MT0305"),
        ("19", "60", 1_001, "MT0305"),
    ]
    again = plan_import(conn, shop.company_id, [einvoice("MT0305", "2026-03-05", 15_000, 1_001)])
    assert again[0].existing == doc.number  # imported once


def test_other_amounts_are_only_offered(shop, conn):
    """The e-qaimə is 155.00 (the purchase 150.00): offered, not chosen. Chosen by the
    user, only the number is written; the lines and their VAT stay for the user."""
    document_id = waiting(shop)
    (plan,) = plan_import(conn, shop.company_id, [einvoice("MT7", "2026-03-05", 15_500, 2_790)])
    assert [p.document_id for p in plan.awaiting] == [document_id]
    assert plan.attach_to is None

    plan.attach_to = plan.awaiting[0]
    import_drafts(shop.inventory, shop.company_id, [plan])
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.invoice, doc.awaits_invoice) == ("MT7", False)
    assert [line.vat_amount for line in doc.lines] == [0, 0]


def test_two_einvoices_take_two_waiting_purchases(shop, conn):
    """Two waiting purchases of 150.00 (02.03, 03.03) and two e-qaimə of 150.00: the
    older e-qaimə takes the older purchase, the next one the other."""
    first, second = waiting(shop, "2026-03-02"), waiting(shop, "2026-03-03")
    plans = plan_import(
        conn,
        shop.company_id,
        [einvoice("MT2", "2026-03-06", 15_000, 0), einvoice("MT1", "2026-03-05", 15_000, 0)],
    )
    chosen = {p.invoice.number: p.attach_to.document_id for p in plans if p.attach_to}
    assert chosen == {"MT1": first, "MT2": second}


def test_a_waiting_draft_and_a_closed_period(shop, conn):
    """A waiting draft takes the e-qaimə as a draft; one in a closed period is not offered."""
    draft = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-10",
        [ReceiptLine(shop.item, shop.main, "1", "20")],
        shop.acc["60"],
        shop.supplier,
        awaits_invoice=True,
    )
    old = waiting(shop, "2026-02-10")
    shop.ledger.set_closed_through(shop.company_id, "2026-02-28")
    (plan,) = plan_import(conn, shop.company_id, [einvoice("MT9", "2026-03-12", 2_000, 360)])
    assert [p.document_id for p in plan.awaiting] == [draft]
    import_drafts(shop.inventory, shop.company_id, [plan])
    doc = shop.inventory.load_document(shop.company_id, draft)
    assert (doc.status, doc.invoice, [ln.vat_amount for ln in doc.lines]) == (
        "draft",
        "MT9",
        [360],
    )
    assert shop.inventory.load_document(shop.company_id, old).awaits_invoice


def test_attach_refuses_a_purchase_that_does_not_wait(shop):
    document_id = shop.receipt("2026-03-01", "1", "10")
    with pytest.raises(ValidationError, match="не ждёт e-qaimə"):
        shop.inventory.attach_invoice(shop.company_id, document_id, "MT1")


def test_purchase_form_marks_a_purchase_waiting(shop, conn, qtbot):
    """«Ждёт e-qaimə» in the basis box: the number field is off and the purchase is saved
    waiting; the list of purchases says so."""
    from PySide6.QtWidgets import QApplication

    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import theme
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.inventory_document_page.form import AWAITING
    from modern_gl.desktop.session import Session
    from modern_gl.desktop.trade_page import TradePage

    draft = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-03-05",
        [ReceiptLine(shop.item, shop.main, "1", "10")],
        shop.acc["60"],
        shop.supplier,
        invoice="MT9",
    )
    theme.apply(QApplication.instance())
    s = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        notify=lambda _m: None,
    )
    page = InventoryDocumentPage(s, doc_type="receipt")
    qtbot.addWidget(page)
    page.load(draft)
    page.basis.setCurrentIndex(page.basis.findData(AWAITING))
    page.basis.activated.emit(page.basis.currentIndex())
    assert page.invoice.text() == "" and not page.invoice.isEnabled()
    assert page.save(post=True)
    doc = shop.inventory.load_document(shop.company_id, draft)
    assert (doc.status, doc.invoice, doc.awaits_invoice) == ("posted", "", True)
    assert page.basis.currentData() == AWAITING  # shown again as saved

    trade = TradePage(s, "receipt")
    qtbot.addWidget(trade)
    assert trade.model.rows[0].awaits_invoice
    assert trade._invoice(trade.model.rows[0]) == "ждёт e-qaimə"


def test_import_dialog_offers_the_waiting_purchase(shop, conn, qtbot):
    """The e-qaimə of the supplier is offered its waiting purchase of the same amount;
    imported, it goes into that purchase, no draft is made."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.eqaime_import_page import BECOMES, EqaimeImportDialog
    from modern_gl.desktop.pick import PickBox
    from modern_gl.desktop.session import Session

    document_id = waiting(shop)
    s = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    dialog = EqaimeImportDialog(s, sign_in=lambda parent: None)
    qtbot.addWidget(dialog)
    dialog.show_invoices([einvoice("MT0305", "2026-03-05", 15_000, 2_700)])
    item = dialog.tree.topLevelItem(0)
    assert item is not None
    box = dialog.tree.itemWidget(item, BECOMES)
    assert isinstance(box, PickBox) and box.count() == 2
    assert box.currentText().startswith("В покупку №")
    assert box.itemText(0).startswith("Новый черновик")
    assert dialog.import_button.text() == "Загрузить: черновиков 0, в покупки 1"
    box.setCurrentIndex(0)
    box.activated.emit(0)
    assert dialog.import_button.text() == "Создать черновики: 1"
    box.setCurrentIndex(1)
    box.activated.emit(1)
    dialog.create_drafts()
    assert (dialog.created, dialog.attached) == ([], [document_id])
    assert dialog.outcome() == "e-qaimə дописана в покупки: 1"
    doc = shop.inventory.load_document(shop.company_id, document_id)
    assert (doc.invoice, sum(line.vat_amount for line in doc.lines)) == ("MT0305", 2_700)


def test_bu_gun_reminds_of_purchases_waiting(shop, conn):
    """Waiting purchases of 02.03 and 03.03: on 03.03 «Bu gün» shows 2, since 02.03; on
    02.03 only the first; once the e-qaimə is in both, nothing."""
    from modern_gl.reporting.overview import attention

    first, second = waiting(shop, "2026-03-02"), waiting(shop, "2026-03-03")

    def rows(day: str) -> list[tuple]:
        return [
            (r.text, r.count, r.place)
            for r in attention(conn, shop.company_id, day)
            if r.place == ("purchases",)
        ]

    assert rows("2026-03-03") == [("Покупки ждут e-qaimə, с 02.03.2026", 2, ("purchases",))]
    assert rows("2026-03-02") == [("Покупки ждут e-qaimə, с 02.03.2026", 1, ("purchases",))]
    shop.inventory.attach_invoice(shop.company_id, first, "MT1")
    shop.inventory.attach_invoice(shop.company_id, second, "MT2")
    assert rows("2026-03-03") == []
