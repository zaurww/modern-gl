"""Purchase and sale drafts posted at once (D73): the e-qaimə of one supplier come every
month and are booked the same way. The numbers are worked out by hand in each docstring."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine, SaleLine
from modern_gl.application.trade_batch import post_drafts
from modern_gl.desktop.session import Session
from modern_gl.desktop.trade_page import TradePage
from modern_gl.reporting.trade import PURCHASE
from tests.test_sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))


def fuel(shop: Shop) -> int:
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    return shop.ledger.add_subconto_value(shop.company_id, kind, "Yanacaq")


def draft(shop: Shop, day: str, memo: str, amount: str, vat: str, supplier=None) -> int:
    """A purchase draft as the e-qaimə import makes it: a line without an item or account."""
    return shop.inventory.create_receipt_draft(
        shop.company_id,
        day,
        [ReceiptLine(None, None, None, amount, memo, vat_amount=vat)],
        shop.acc["60"],
        supplier or shop.supplier,
        vat_rate=STANDARD_VAT_RATE,
    )


def socar_month(shop: Shop) -> tuple[int, int, int, int]:
    """January, posted by hand: «Aİ-92» 100.00 + VAT 18.00 to Dt 26 [Yanacaq]. February
    drafts: «Aİ-92» 50.00 + 9.00 and «Dizel» 30.00 + 5.40 of the same supplier, and a
    phone bill 20.00 + 3.60 of a supplier never booked before."""
    yanacaq = fuel(shop)
    shop.inventory.post_receipt(
        shop.company_id,
        "2026-01-10",
        [
            ReceiptLine(
                None,
                None,
                None,
                "100",
                "Aİ-92",
                vat_amount="18",
                expense_account_id=shop.acc["26"],
                expense_subconto=[yanacaq],
            )
        ],
        shop.acc["60"],
        shop.supplier,
        vat_rate=STANDARD_VAT_RATE,
    )
    kind = shop.ledger.subconto_kind_id(shop.company_id, "counterparty")
    phone = shop.ledger.add_subconto_value(shop.company_id, kind, "Rabitə MMC")
    petrol = draft(shop, "2026-02-10", "Aİ-92", "50", "9")
    diesel = draft(shop, "2026-02-20", "Dizel", "30", "5.40")
    bill = draft(shop, "2026-02-15", "Rabitə xidməti", "20", "3.60", [phone])
    return yanacaq, petrol, diesel, bill


def test_drafts_post_with_the_account_of_the_last_purchase(shop, conn):
    """«Aİ-92» goes where it went in January; «Dizel» was never bought — it takes the
    supplier's last expense line, the same Dt 26 [Yanacaq]:
      Dt 26 / Kt 60  50.00   Dt 19 / Kt 60  9.00
      Dt 26 / Kt 60  30.00   Dt 19 / Kt 60  5.40
    The phone bill has nothing to learn from: it stays a draft, with the reason."""
    yanacaq, petrol, diesel, bill = socar_month(shop)
    bill_number = shop.inventory.load_document(shop.company_id, bill).number

    result = post_drafts(shop.inventory, shop.company_id, [diesel, bill, petrol])

    assert result.posted == [petrol, diesel]  # in date order
    assert result.filled == 2
    assert result.failed == [(bill_number, "строка 1: не указан счёт затрат")]
    assert [p[:3] for p in shop.postings(petrol)] == [("26", "60", 5_000), ("19", "60", 900)]
    assert [p[:3] for p in shop.postings(diesel)] == [("26", "60", 3_000), ("19", "60", 540)]
    line = shop.inventory.load_document(shop.company_id, diesel).lines[0]
    assert (line.cost_account_id, line.cost_subconto) == (shop.acc["26"], (yanacaq, None, None))
    rest = shop.inventory.load_document(shop.company_id, bill)
    assert rest.status == "draft" and rest.lines[0].cost_account_id is None  # rolled back


def test_a_service_known_from_another_supplier_is_filled_from_it(shop, conn):
    """«Aİ-92» of a petrol station never booked before: nothing of its own to learn from,
    so the line takes the account of the same fuel bought from the first supplier
    (January, Dt 26 [Yanacaq]): Dt 26 / Kt 60 40.00, Dt 19 / Kt 60 7.20."""
    yanacaq, *_ = socar_month(shop)
    kind = shop.ledger.subconto_kind_id(shop.company_id, "counterparty")
    station = shop.ledger.add_subconto_value(shop.company_id, kind, "Azpetrol")
    other = draft(shop, "2026-02-12", "aİ-92", "40", "7.20", [station])

    result = post_drafts(shop.inventory, shop.company_id, [other])

    assert (result.posted, result.filled, result.failed) == ([other], 1, [])
    assert [p[:3] for p in shop.postings(other)] == [("26", "60", 4_000), ("19", "60", 720)]
    line = shop.inventory.load_document(shop.company_id, other).lines[0]
    assert line.cost_subconto == (yanacaq, None, None)


def test_an_account_typed_in_the_draft_is_kept(shop, conn):
    """A line whose account the user chose (26 [Təmir]) keeps it: the history (26
    [Yanacaq]) fills only empty lines. Dt 26 / Kt 60 10.00."""
    socar_month(shop)
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    repair = shop.ledger.add_subconto_value(shop.company_id, kind, "Təmir")
    typed = shop.inventory.create_receipt_draft(
        shop.company_id,
        "2026-02-25",
        [
            ReceiptLine(
                None,
                None,
                None,
                "10",
                "Aİ-92",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            )
        ],
        shop.acc["60"],
        shop.supplier,
    )
    result = post_drafts(shop.inventory, shop.company_id, [typed])
    assert (result.posted, result.filled, result.failed) == ([typed], 0, [])
    assert [p[:3] for p in shop.postings(typed)] == [("26", "60", 1_000)]
    line = shop.inventory.load_document(shop.company_id, typed).lines[0]
    assert line.cost_subconto == (repair, None, None)


def test_purchases_page_posts_the_filtered_drafts(shop, conn, qtbot):
    """The search leaves the supplier's two drafts: the button posts them; the other
    supplier's draft is not touched."""
    _, petrol, diesel, bill = socar_month(shop)
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = TradePage(session, PURCHASE)
    qtbot.addWidget(page)
    assert page.post_button.text() == "Провести черновики: 3"

    page.search.setText("techizat")  # «Təchizatçı», as typed without the letters
    assert {r.id for r in page.drafts_to_post()} == {petrol, diesel}
    assert page.post_button.text() == "Провести черновики: 2"
    with qtbot.waitSignal(page.imported):
        page.post_button.click()
    statuses = {r.id: r.status for r in page.model.rows}
    assert statuses[petrol] == statuses[diesel] == "posted"
    assert page.post_button.isHidden()  # nothing left to post in the list

    page.search.setText("")
    assert [r.id for r in page.drafts_to_post()] == [bill]
    page.table.selectRow(0)  # one selected row: still the whole list
    assert [r.id for r in page.drafts_to_post()] == [bill]


def test_sale_drafts_post_too(shop, conn):
    """Two delivery services to Alfa, 25.00 and 40.00 without VAT: Dt 62 / Kt 46 each."""
    drafts = [
        shop.inventory.create_sale_draft(
            shop.company_id,
            day,
            [SaleLine(None, None, None, amount, memo="Çatdırılma")],
            shop.acc["62"],
            [shop.customer, shop.contract],
        )
        for day, amount in (("2026-02-03", "25"), ("2026-02-17", "40"))
    ]
    result = post_drafts(shop.inventory, shop.company_id, drafts)
    assert (result.posted, result.failed) == (drafts, [])
    assert [p[:3] for p in shop.postings(drafts[0])] == [("62", "46", 2_500)]
    assert [p[:3] for p in shop.postings(drafts[1])] == [("62", "46", 4_000)]
