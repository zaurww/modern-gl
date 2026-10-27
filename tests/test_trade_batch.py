"""Purchase and sale drafts posted at once (D73): the e-qaimə of one supplier come every
month and are booked the same way. The numbers are worked out by hand in each docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine, SaleLine
from modern_gl.application.trade_batch import (
    Booking,
    OpenLines,
    open_lines,
    post_drafts,
)
from modern_gl.desktop.batch_post_dialog import BatchPostDialog
from modern_gl.desktop.session import Session
from modern_gl.desktop.trade_page import TradePage
from modern_gl.reporting.trade import PURCHASE
from tests.helpers.sale_subconto import postings_46, sales_groups
from tests.helpers.sales import Shop, make_shop
from tests.helpers.uniform_entry import shown

pytestmark = pytest.mark.questions("Yes")  # deleting, posting: yes


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


@pytest.fixture(autouse=True)
def batch_dialog_posts(monkeypatch):
    monkeypatch.setattr(BatchPostDialog, "exec", lambda self: 1)  # «Провести», empty


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


def test_purchases_page_deletes_the_marked_documents(shop, conn, qtbot):
    """Two of the three February drafts marked: Del deletes them, the third stays."""
    _, petrol, diesel, bill = socar_month(shop)
    page = shown(qtbot, TradePage(session_of(shop, conn), PURCHASE))
    marked = [i for i, r in enumerate(page.model.rows) if r.id in (petrol, diesel)]
    flags = QItemSelectionModel.SelectionFlag
    for i in marked:
        page.table.selectionModel().select(page.model.index(i, 0), flags.Select | flags.Rows)
    page.table.setFocus()
    with qtbot.waitSignal(page.imported):
        qtbot.keyClick(page.table, Qt.Key.Key_Delete)
    ids = {r.id for r in page.model.rows}
    assert bill in ids and not ids & {petrol, diesel}


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


def rabite(shop: Shop) -> int:
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    return shop.ledger.add_subconto_value(shop.company_id, kind, "Rabitə")


def test_open_lines_offer_where_they_went_last_time(shop, conn):
    """«Aİ-92» and «Dizel» of the supplier both went to 26 [Yanacaq] (January): that is
    offered. With the phone bill, which never went anywhere, nothing is offered."""
    yanacaq, petrol, diesel, bill = socar_month(shop)
    lines = open_lines(shop.inventory, shop.company_id, [petrol, diesel])
    booked = Booking(shop.acc["26"], (yanacaq, None, None))
    assert lines == OpenLines("receipt", 2, booked, shop.acc["60"])
    lines = open_lines(shop.inventory, shop.company_id, [petrol, bill])
    assert (lines.count, lines.suggested) == (2, None)


def test_the_chosen_account_goes_to_every_open_line(shop, conn):
    """26 [Rabitə] chosen for the batch goes to the phone bill, never booked, and to
    «Aİ-92» too, though it went to 26 [Yanacaq] in January:
      bill    Dt 26 / Kt 60  20.00   Dt 19 / Kt 60  3.60
      petrol  Dt 26 / Kt 60  50.00   Dt 19 / Kt 60  9.00
    Posted, it is remembered: the next phone bill offers 26 [Rabitə]."""
    _, petrol, _, bill = socar_month(shop)
    phone_item = rabite(shop)
    chosen = Booking(shop.acc["26"], (phone_item, None, None))

    result = post_drafts(shop.inventory, shop.company_id, [bill, petrol], chosen)

    assert (result.posted, result.filled, result.failed) == ([petrol, bill], 2, [])
    assert [p[:3] for p in shop.postings(bill)] == [("26", "60", 2_000), ("19", "60", 360)]
    assert [p[:3] for p in shop.postings(petrol)] == [("26", "60", 5_000), ("19", "60", 900)]
    for doc in (bill, petrol):
        line = shop.inventory.load_document(shop.company_id, doc).lines[0]
        assert line.cost_subconto == (phone_item, None, None)
    phone = shop.inventory.load_document(shop.company_id, bill).lines[0].offset_subconto
    march = draft(shop, "2026-03-15", "Rabitə xidməti", "20", "3.60", [phone[0]])
    assert open_lines(shop.inventory, shop.company_id, [march]).suggested == chosen


def test_the_chosen_credit_account_goes_to_the_open_lines(shop, conn):
    """The phone bill 20.00 + 3.60 of «Rabitə MMC» booked to 26 [Rabitə] against 76, not
    the 60 the import put in; the supplier moves with it (76 has «Контрагенты» too):
      Dt 26 [Rabitə] / Kt 76 [Rabitə MMC]  20.00    Dt 19 / Kt 76 [Rabitə MMC]  3.60
    The window offers the 60 the open lines have now."""
    _, _, _, bill = socar_month(shop)
    phone_item = rabite(shop)
    lines = open_lines(shop.inventory, shop.company_id, [bill])
    assert lines.offset_account_id == shop.acc["60"]
    party = shop.inventory.load_document(shop.company_id, bill).lines[0].offset_subconto[0]
    chosen = Booking(shop.acc["26"], (phone_item, None, None), shop.acc["76"])

    result = post_drafts(shop.inventory, shop.company_id, [bill], chosen)

    assert (result.posted, result.failed) == ([bill], [])
    assert [p[:3] for p in shop.postings(bill)] == [("26", "76", 2_000), ("19", "76", 360)]
    line = shop.inventory.load_document(shop.company_id, bill).lines[0]
    assert (line.offset_account_id, line.offset_subconto) == (shop.acc["76"], (party, None, None))


def test_sale_drafts_take_the_chosen_sales_group(shop, conn):
    """46 carries «Satış qrupları». Two deliveries to Alfa, 25.00 and 40.00 without VAT,
    never sold before: nothing offered; «Xidmət» chosen for both:
      Dt 62 / Kt 46 [Xidmət]  25.00     Dt 62 / Kt 46 [Xidmət]  40.00
    The next delivery offers «Xidmət»."""
    _, (service, _) = sales_groups(shop, "Xidmət", "Topdan")

    def delivery(day: str, amount: str) -> int:
        return shop.inventory.create_sale_draft(
            shop.company_id,
            day,
            [SaleLine(None, None, None, amount, memo="Çatdırılma")],
            shop.acc["62"],
            [shop.customer, shop.contract],
        )

    drafts = [delivery("2026-02-03", "25"), delivery("2026-02-17", "40")]
    assert open_lines(shop.inventory, shop.company_id, drafts) == OpenLines("sale", 2, None)

    result = post_drafts(shop.inventory, shop.company_id, drafts, Booking(None, (service,)))

    assert (result.posted, result.filled, result.failed) == (drafts, 2, [])
    assert postings_46(shop, conn, drafts[0]) == [("62", "46", 2_500, service)]
    assert postings_46(shop, conn, drafts[1]) == [("62", "46", 4_000, service)]
    later = delivery("2026-03-03", "10")
    assert open_lines(shop.inventory, shop.company_id, [later]).suggested == Booking(
        None, (service,)
    )


def session_of(shop: Shop, conn) -> Session:
    return Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))


def test_dialog_offers_last_time_and_posts_on_enter(shop, conn, qtbot):
    """Opened on the supplier's two drafts, the window has 26 and «Yanacaq» filled in:
    Enter on «Провести» books them there."""
    yanacaq, petrol, diesel, _ = socar_month(shop)
    session = session_of(shop, conn)
    lines = open_lines(shop.inventory, shop.company_id, [petrol, diesel])
    dialog = BatchPostDialog(session, 2, "Təchizatçı", lines, [])
    qtbot.addWidget(dialog)
    assert dialog.account is not None
    assert dialog.account.currentData() == shop.acc["26"]
    assert [f.currentData() for _, f in dialog.fields] == [yanacaq]
    dialog.show()
    qtbot.waitUntil(dialog.ok.hasFocus)  # all filled: the cursor waits on «Провести»
    qtbot.keyClick(dialog.ok, Qt.Key.Key_Return)
    assert dialog.result() == 1
    assert dialog.booking == Booking(shop.acc["26"], (yanacaq, None, None))


def test_dialog_asks_for_the_subconto_the_account_needs(shop, conn, qtbot):
    """Nothing offered (the phone bill): 26 typed, Enter goes to «Статья затрат», not past
    it; «Провести» with it empty says what is missing; chosen — the batch goes there."""
    _, _, _, bill = socar_month(shop)
    phone_item = rabite(shop)
    session = session_of(shop, conn)
    lines = open_lines(shop.inventory, shop.company_id, [bill])
    dialog = BatchPostDialog(session, 1, "Rabitə MMC", lines, [])
    qtbot.addWidget(dialog)
    dialog.show()
    account = dialog.account
    assert account is not None and account.currentData() is None
    account.setFocus()
    account.setText("26")
    qtbot.keyClick(account, Qt.Key.Key_Return)
    assert account.currentData() == shop.acc["26"]
    ((_, item),) = dialog.fields
    qtbot.waitUntil(item.hasFocus)
    qtbot.keyClick(item, Qt.Key.Key_Return)  # empty: Enter does not post
    assert dialog.isVisible()
    dialog.ok.click()
    assert dialog.isVisible() and not dialog.error.isHidden()
    item.setCurrentIndex(item.findData(phone_item))
    dialog.ok.click()
    assert dialog.result() == 1
    assert dialog.booking == Booking(shop.acc["26"], (phone_item, None, None))


def test_dialog_left_empty_posts_like_last_time(shop, conn, qtbot):
    """No account chosen: no booking, each line goes where it went the last time."""
    _, petrol, _, bill = socar_month(shop)
    lines = open_lines(shop.inventory, shop.company_id, [petrol, bill])
    dialog = BatchPostDialog(session_of(shop, conn), 2, "", lines, [])
    qtbot.addWidget(dialog)
    dialog.ok.click()
    assert (dialog.result(), dialog.booking) == (1, None)


def test_dialog_takes_another_credit_account_and_adds_a_cost_item(shop, conn, qtbot):
    """The phone bill: 26, a cost item not in the directory yet — «+ Добавить «Mobil
    rabitə»» adds it right there; Kt 60 as imported is changed to 76."""
    _, _, _, bill = socar_month(shop)
    session = session_of(shop, conn)
    lines = open_lines(shop.inventory, shop.company_id, [bill])
    dialog = BatchPostDialog(session, 1, "Rabitə MMC", lines, [])
    qtbot.addWidget(dialog)
    assert dialog.account is not None and dialog.offset is not None
    assert dialog.offset.currentData() == shop.acc["60"]  # what the drafts have
    dialog.account.setCurrentIndex(dialog.account.findData(shop.acc["26"]))
    dialog._account_chosen()
    ((_, item),) = dialog.fields
    item.added.emit("Mobil rabitə")
    new = item.currentData()
    assert new is not None and session.catalog.value(new).name == "Mobil rabitə"
    dialog.offset.setCurrentIndex(dialog.offset.findData(shop.acc["76"]))
    dialog.ok.click()
    assert dialog.booking == Booking(shop.acc["26"], (new, None, None), shop.acc["76"])
