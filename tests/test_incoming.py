"""«Mədaxil» (D91): goods come in without a purchase — Dt stock / Kt the reason's account."""

from datetime import date

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import QUANTITY_FACTOR, IssueLine, ReceiptLine
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.session import Session
from modern_gl.domain.accounts import FX_GAIN, INCOMING_PRODUCTION, INCOMING_SURPLUS
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.inventory import stock_balances, stock_card
from modern_gl.reporting.reports import trial_balance
from tests.test_inventory import InventoryDemo, inventory_demo  # noqa: F401 — the fixture


def other_income(demo: InventoryDemo) -> int:
    return demo.inventory.ledger.add_account(
        demo.company_id, "631", "Прочие доходы", account_class="revenue"
    )


def test_surplus_comes_in_against_other_income(inventory_demo, conn):  # noqa: F811
    demo = inventory_demo
    income = other_income(demo)
    demo.inventory.ledger.set_account_role(demo.company_id, INCOMING_SURPLUS, income)
    assert demo.inventory.incoming_account(demo.company_id, "surplus") == income
    found = demo.inventory.post_receipt(  # 5 pcs found at the count, worth 50.00
        demo.company_id,
        "2026-01-15",
        [ReceiptLine(demo.item, demo.main, "5", "50.00")],
        income,
        incoming_reason="surplus",
    )
    doc = demo.inventory.load_document(demo.company_id, found)
    assert (doc.doc_type, doc.incoming_reason, doc.vat_rate) == ("incoming", "surplus", None)
    [balance] = stock_balances(conn, demo.company_id)
    assert (balance.quantity, balance.amount) == (5 * QUANTITY_FACTOR, 5_000)
    [line] = stock_card(conn, demo.company_id, demo.item, demo.main)
    assert (line.source.doc_type, line.source.movement_type) == ("incoming", "receipt")
    # the found goods are issued at their value: 2 of 5 at 10.00 each
    demo.inventory.post_issue(
        demo.company_id, "2026-01-20", [IssueLine(demo.item, demo.main, "2", demo.expense_account)]
    )
    osv = {
        row.code: row
        for row in trial_balance(conn, demo.company_id, "2026-01-01", "2026-01-31").rows
    }
    assert osv["631"].turnover_ct == 5_000  # Dt 41 / Kt 631 50.00
    assert osv["41"].closing_dt == 3_000  # 50.00 in, 20.00 out
    assert osv["46"].turnover_dt == 2_000


def test_gift_without_an_account_of_its_own_is_other_income(inventory_demo):  # noqa: F811
    demo = inventory_demo
    income = other_income(demo)
    assert demo.inventory.incoming_account(demo.company_id, "gift") is None
    demo.inventory.ledger.set_account_role(demo.company_id, FX_GAIN, income)
    assert demo.inventory.incoming_account(demo.company_id, "gift") == income
    assert demo.inventory.incoming_account(demo.company_id, "production") is None


def test_draft_keeps_its_reason_and_takes_goods_only(inventory_demo):  # noqa: F811
    demo = inventory_demo
    income = other_income(demo)
    inv = demo.inventory
    draft = inv.create_receipt_draft(
        demo.company_id,
        "2026-01-15",
        [ReceiptLine(demo.item, demo.main, "1", "10")],
        income,
        incoming_reason="gift",
    )
    lines = [ReceiptLine(demo.item, demo.main, "2", "30")]
    inv.update_receipt_draft(
        demo.company_id, draft, "2026-01-16", lines, income, incoming_reason="contribution"
    )
    assert inv.load_document(demo.company_id, draft).incoming_reason == "contribution"
    with pytest.raises(ValidationError, match="не указан товар"):  # only a purchase has services
        inv.update_receipt_draft(
            demo.company_id,
            draft,
            "2026-01-16",
            [ReceiptLine(None, None, "1", "10", memo="Çatdırılma")],
            income,
            incoming_reason="contribution",
        )
    with pytest.raises(ValidationError, match="тип складского документа"):
        inv.update_receipt_draft(  # a mədaxil does not turn into a purchase
            demo.company_id, draft, "2026-01-16", [], income
        )
    with pytest.raises(ValidationError, match="неизвестная причина"):
        inv.create_receipt_draft(demo.company_id, "2026-01-15", [], income, incoming_reason="theft")


def test_incoming_form_takes_the_reasons_account(inventory_demo, conn, qtbot):  # noqa: F811
    demo = inventory_demo
    income, production = other_income(demo), demo.expense_account
    ledger = demo.inventory.ledger
    ledger.set_account_role(demo.company_id, INCOMING_SURPLUS, income)
    ledger.set_account_role(demo.company_id, INCOMING_PRODUCTION, production)
    session = Session(
        conn,
        ledger,
        demo.company_id,
        "Склад",
        Catalog(conn, demo.company_id),
        working_date=date(2026, 1, 15),
    )
    page = InventoryDocumentPage(session, doc_type="incoming")
    qtbot.addWidget(page)
    assert not page.reason.isHidden() and page.basis.isHidden()  # a reason, no e-qaimə
    assert page.model.rows[0].offset_account_id == income  # a surplus by default
    page.reason.setCurrentIndex(page.reason.findData("production"))
    page._reason_changed()
    assert page.model.rows[0].offset_account_id == production
    page.model.rows[0].item_id, page.model.rows[0].warehouse_id = demo.item, demo.main
    page.model.rows[0].quantity, page.model.rows[0].amount = 3 * QUANTITY_FACTOR, 4_500
    assert page.save(post=True)
    doc = demo.inventory.load_document(demo.company_id, page.document_id)
    assert (doc.doc_type, doc.incoming_reason, doc.status) == ("incoming", "production", "posted")
    assert doc.lines[0].offset_account_id == production  # Dt 41 / Kt the production account
