"""D211: a service of a purchase that waits on 15 goes into a batch's cost with one tick; the
amounts below are counted by hand."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import (
    Inventory,
    LandedCostCharge,
    LandedCostTarget,
    ReceiptLine,
)
from modern_gl.application.ledger import Ledger
from modern_gl.desktop.landed_cost_page import ChargeRow, LandedCostPage
from modern_gl.desktop.landed_cost_page import page as page_module
from modern_gl.desktop.landed_cost_page.waiting_expenses import WaitingExpensesDialog
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import Connection, connect
from modern_gl.reporting.inventory import waiting_expenses, waiting_lines
from modern_gl.reporting.inventory.costs import expenses_waiting_a_batch
from modern_gl.reporting.reports import trial_balance


@dataclass
class Shop:
    conn: Connection
    ledger: Ledger
    inventory: Inventory
    cid: int
    goods: int  # the purchase of a declaration: 10 pieces for 1 000.00
    goods_line: int
    service_doc: int  # the broker's e-qaimə: 640.00 and 30.00 of another declaration
    service_line: int
    other_line: int
    procurement: int
    payable: int
    customs: int
    main: int
    item: int
    supplier: int


@pytest.fixture
def shop():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    item_kind = ledger.add_subconto_kind(cid, "item", "Mallar")
    warehouse_kind = ledger.add_subconto_kind(cid, "warehouse", "Anbarlar")
    party_kind = ledger.add_subconto_kind(cid, "counterparty", "Kontragentlər")
    stock = ledger.add_account(
        cid,
        "41",
        "Mallar",
        subconto=[item_kind, warehouse_kind],
        account_class="asset",
        account_type="inventory",
    )
    procurement = ledger.add_account(
        cid, "15", "Tədarük", account_class="asset", account_type="inventory"
    )
    payable = ledger.add_account(
        cid, "60", "Malsatan", subconto=[party_kind], account_class="liability"
    )
    supplier = ledger.add_subconto_value(cid, party_kind, "Vial Kas")
    broker = ledger.add_subconto_value(cid, party_kind, "UNİTED CUSTOMS")
    customs = ledger.add_subconto_value(cid, party_kind, "Gömrük")
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "ədəd", "ədəd")
    item = inventory.add_item(cid, "Datçik", unit, stock)
    main = inventory.add_warehouse(cid, "Əsas anbar")
    goods = inventory.post_receipt(
        cid,
        "2026-09-21",
        [ReceiptLine(item, main, "10", "1000")],
        payable,
        [supplier],
        invoice="01261000379327",
        invoice_kind="customs",
    )
    service_doc = inventory.post_receipt(
        cid,
        "2026-09-28",
        [
            ReceiptLine(
                None,
                None,
                None,
                "640",
                "Xidmət YGB №01261000379327",
                expense_account_id=procurement,
            ),
            ReceiptLine(
                None,
                None,
                None,
                "30",
                "Xidmət YGB №11265000255540",
                expense_account_id=procurement,
            ),
        ],
        payable,
        [broker],
    )
    goods_line = inventory.load_document(cid, goods).lines[0].id
    service, other = inventory.load_document(cid, service_doc).lines
    yield Shop(
        conn,
        ledger,
        inventory,
        cid,
        goods,
        goods_line,
        service_doc,
        service.id,
        other.id,
        procurement,
        payable,
        customs,
        main,
        item,
        supplier,
    )
    conn.close()


def balance(shop: Shop, account_code: str) -> tuple[int, int]:
    """(debit, credit) of an account's closing balance."""
    osv = trial_balance(shop.conn, shop.cid, date(2026, 1, 1), date(2026, 12, 31))
    row = next(r for r in osv.rows if r.code == account_code)
    return row.closing_dt, row.closing_ct


def batch(shop: Shop, day: str, *charges: LandedCostCharge) -> int:
    return shop.inventory.create_landed_cost_draft(
        shop.cid, day, [LandedCostTarget(shop.goods_line)], list(charges)
    )


def test_the_service_moves_from_15_to_the_goods_and_no_new_debt_comes(shop):
    """60: 1 000.00 + 670.00 = 1 670.00 before and after. 15: 670.00 - 640.00 = 30.00, what
    is left of the other declaration. 41: 1 000.00 + 640.00 = 1 640.00."""
    assert balance(shop, "60") == (0, 167_000)
    assert balance(shop, "15") == (67_000, 0)
    doc = batch(shop, "2026-09-28", LandedCostCharge("640", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, doc)
    assert balance(shop, "60") == (0, 167_000)
    assert balance(shop, "15") == (3_000, 0)
    assert balance(shop, "41") == (164_000, 0)
    left = [(row.line_id, row.left) for row in waiting_lines(shop.conn, shop.cid)]
    assert left == [(shop.other_line, 3_000)]


def test_a_service_cannot_be_taken_beyond_what_it_is(shop):
    first = batch(shop, "2026-09-28", LandedCostCharge("600", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, first)
    second = batch(shop, "2026-09-28", LandedCostCharge("41", source_line_id=shop.service_line))
    with pytest.raises(ValidationError, match=r"40.00"):  # 640.00 - 600.00
        shop.inventory.post_document(shop.cid, second)


def test_a_batch_cannot_be_earlier_than_the_service(shop):
    doc = batch(shop, "2026-09-21", LandedCostCharge("640", source_line_id=shop.service_line))
    with pytest.raises(ValidationError):
        shop.inventory.post_document(shop.cid, doc)


def test_only_a_service_of_a_purchase_can_be_taken(shop):
    with pytest.raises(ValidationError):
        batch(shop, "2026-09-28", LandedCostCharge("1", source_line_id=shop.goods_line))


def test_a_taken_service_stays_in_its_purchase(shop):
    """Its line cannot go, not even from a draft of the batch."""
    batch(shop, "2026-09-28", LandedCostCharge("640", source_line_id=shop.service_line))
    with pytest.raises(ValidationError):
        shop.inventory.delete_document(shop.cid, shop.service_doc)


def test_a_purchase_posted_again_keeps_the_batch(shop):
    """The purchase is edited in place: a new line before the service renumbers its postings;
    the batch follows the line. 15: 30 + 5 = 35.00 left."""
    doc = batch(shop, "2026-09-30", LandedCostCharge("640", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, doc)
    lines = shop.inventory.load_document(shop.cid, shop.service_doc).lines
    new = ReceiptLine(None, None, None, "5", "Əlavə", expense_account_id=shop.procurement)
    kept = [
        ReceiptLine(
            None,
            None,
            None,
            Decimal(line.amount) / 100,
            line.memo,
            line_id=line.id,
            expense_account_id=shop.procurement,
        )
        for line in lines
    ]
    credit = shop.inventory.load_document(shop.cid, shop.service_doc)
    with shop.inventory.reposting(shop.cid, shop.service_doc):
        shop.inventory.update_receipt_draft(
            shop.cid,
            shop.service_doc,
            "2026-09-28",
            [new, *kept],
            shop.payable,
            [credit.lines[0].offset_subconto[0]],
        )
    assert balance(shop, "15") == (3_500, 0)
    assert balance(shop, "41") == (164_000, 0)


def test_a_service_made_smaller_than_taken_is_refused(shop):
    doc = batch(shop, "2026-09-30", LandedCostCharge("640", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, doc)
    lines = shop.inventory.load_document(shop.cid, shop.service_doc).lines
    smaller = [
        ReceiptLine(
            None,
            None,
            None,
            "100",
            line.memo,
            line_id=line.id,
            expense_account_id=shop.procurement,
        )
        for line in lines
    ]
    with (
        pytest.raises(ValidationError),
        shop.inventory.reposting(shop.cid, shop.service_doc),
    ):
        shop.inventory.update_receipt_draft(
            shop.cid,
            shop.service_doc,
            "2026-09-28",
            smaller,
            shop.payable,
            [lines[0].offset_subconto[0]],
        )
    assert balance(shop, "41") == (164_000, 0)


def test_a_purchase_with_a_taken_service_is_not_unposted_under_the_batch(shop):
    doc = batch(shop, "2026-09-30", LandedCostCharge("640", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, doc)
    with pytest.raises(ValidationError):
        shop.inventory.unpost_document(shop.cid, shop.service_doc)
    assert balance(shop, "41") == (164_000, 0)


def test_rebuilding_changes_nothing(shop):
    doc = batch(shop, "2026-09-28", LandedCostCharge("640", source_line_id=shop.service_line))
    shop.inventory.post_document(shop.cid, doc)
    assert shop.inventory.rebuild_postings(shop.cid, "2026-01-01") == []


def test_bu_gun_tells_what_waits(shop):
    (row,) = expenses_waiting_a_batch(shop.conn, shop.cid, "2026-10-01")
    assert (row.count, row.amount) == (2, 67_000)
    assert expenses_waiting_a_batch(shop.conn, shop.cid, "2026-09-01") == []


def session_of(shop: Shop) -> Session:
    session = Session(
        shop.conn,
        shop.ledger,
        shop.cid,
        "Firma",
        Catalog(shop.conn, shop.cid),
        notify=lambda _message: None,
    )
    session.working_date = date(2026, 9, 30)
    return session


def test_the_window_ticks_what_names_the_declaration(shop, qtbot):
    rows = waiting_expenses(shop.conn, shop.cid)
    dialog = WaitingExpensesDialog(rows, {"01261000379327"})
    qtbot.addWidget(dialog)
    assert [row.line_id for row in dialog.chosen()] == [shop.service_line]
    at = [row.line_id for row in dialog.model.rows].index(shop.other_line)
    dialog.model.setData(
        dialog.model.index(at, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    assert {row.line_id for row in dialog.chosen()} == {shop.service_line, shop.other_line}


def test_the_page_takes_a_ticked_service_and_posts_it(shop, qtbot, monkeypatch):
    monkeypatch.setattr(WaitingExpensesDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)
    page = LandedCostPage(session_of(shop))
    qtbot.addWidget(page)
    page.add_waiting({"01261000379327"})
    taken = [row for row in page.charges.rows if row.taken]
    assert [row.amount for row in taken] == [64_000]
    assert not page.charges.editable(page.charges.rows.index(taken[0]), "account")


def test_a_typed_twin_of_a_waiting_service_is_caught(shop, qtbot, monkeypatch):
    """640.00 typed on 60 would be owed twice: taken instead, the debt stays 1 670.00."""
    monkeypatch.setattr(
        page_module.QMessageBox if hasattr(page_module, "QMessageBox") else QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    page = LandedCostPage(session_of(shop))
    qtbot.addWidget(page)
    page.targets.add(
        [
            line
            for line in page_module.receipt_line_choices(shop.conn, shop.cid)
            if line.id == shop.goods_line
        ]
    )
    page.charges.rows[:] = [ChargeRow(account_id=shop.payable, amount=64_000)]
    assert page.save(True), page.error.text()
    assert balance(shop, "60") == (0, 167_000)
    assert balance(shop, "15") == (3_000, 0)
