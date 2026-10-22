"""Sale accounts with subconto (D61): a sales group on 46 (90.1 / 90.2 / 90.3), filled from
the sale line; a subconto added to an account that already has postings.

The numbers are worked out by hand in each test's docstring."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.eqaime_import import import_drafts, parse_invoice, plan_import
from modern_gl.application.inventory import QUANTITY_FACTOR, ReceiptLine, SaleLine
from modern_gl.application.queries import remembered_sale_subconto
from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.inventory_document_page import (
    AMOUNT,
    ITEM,
    MEMO,
    QUANTITY,
    SALE1,
    SALE2,
    SC1,
    WAREHOUSE,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import subconto_balance
from tests.test_sales import Shop, make_shop, sale_page


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def sales_groups(shop: Shop, *names: str) -> tuple[int, list[int]]:
    """A directory «Satış qrupları» on 46 and its elements."""
    kind = shop.ledger.add_subconto_kind(shop.company_id, None, "Satış qrupları")
    groups = [shop.ledger.add_subconto_value(shop.company_id, kind, name) for name in names]
    shop.ledger.update_account(shop.company_id, shop.acc["46"], subconto=[kind])
    return kind, groups


def postings_46(shop: Shop, conn, inv_doc: int) -> list[tuple]:
    """(Dt, Kt, amount, the sales group on the 46 side) of a document's postings."""
    gl = shop.inventory.load_document(shop.company_id, inv_doc).gl_document_id
    code = {v: k for k, v in shop.acc.items()}
    acc46 = shop.acc["46"]
    return [
        (
            code[p["debit_account_id"]],
            code[p["credit_account_id"]],
            p["amount"],
            p["dt_sc1"]
            if p["debit_account_id"] == acc46
            else p["ct_sc1"]
            if p["credit_account_id"] == acc46
            else None,
        )
        for p in conn.execute(
            "SELECT * FROM postings WHERE document_id = ? ORDER BY line_no", (gl,)
        )
    ]


def test_sales_group_on_46_splits_revenue_cost_and_vat(shop, conn):
    """46 carries «Satış qrupları». 10 printers in for 120.00 (12.00 each). Sold 3 printers
    for 60.00 + VAT 10.80 (group «Printerlər») and delivery for 25.00 + VAT 4.50 (group
    «Xidmətlər»). The VAT posting splits by group, 46 takes the group on every side:
      62 / 46   70.80  Printerlər   (60.00 + 10.80)
      62 / 46   29.50  Xidmətlər    (25.00 + 4.50)
      46 / 68.2 10.80  Printerlər
      46 / 68.2  4.50  Xidmətlər
      46 / 41   36.00  Printerlər   (3 × 12.00)
    ОСВ of 46 by group: Printerlər Dt 46.80 (10.80 + 36.00) / Kt 70.80 — 24.00 margin
    (60.00 - 36.00); Xidmətlər Dt 4.50 / Kt 29.50 — 25.00."""
    _, (printers, services) = sales_groups(shop, "Printerlər", "Xidmətlər")
    shop.receipt("2026-01-10", "10", "120")
    sale = shop.sale(
        "2026-01-20",
        [
            SaleLine(shop.item, shop.main, "3", "60", "10.80", sale_subconto=[printers]),
            SaleLine(None, None, None, "25", "4.50", "Çatdırılma", sale_subconto=[services]),
        ],
    )
    assert postings_46(shop, conn, sale) == [
        ("62", "46", 7_080, printers),
        ("62", "46", 2_950, services),
        ("46", "68.2", 1_080, printers),
        ("46", "68.2", 450, services),
        ("46", "41", 3_600, printers),
    ]
    rows = {
        row.name: (row.turnover_dt, row.turnover_ct, row.closing_ct)
        for row in subconto_balance(conn, shop.company_id, "46", "2026-01-01", "2026-01-31")
    }
    assert rows == {"Printerlər": (4_680, 7_080, 2_400), "Xidmətlər": (450, 2_950, 2_500)}
    goods, service = shop.inventory.load_document(shop.company_id, sale).lines
    assert (goods.cost_subconto, service.cost_subconto) == (
        (printers, None, None),
        (services, None, None),
    )


def test_sale_without_the_group_is_not_posted(shop):
    """46 asks for the group; a line without one says which and why."""
    sales_groups(shop, "Printerlər")
    shop.receipt("2026-01-10", "10", "120")
    with pytest.raises(ValidationError, match=r"строка 1: укажите «Satış qrupları».*46"):
        shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "3", "60", "10.80")])


def test_1c77_chart_takes_the_group_on_90_1_90_2_and_90_3(conn):
    """1C 7.7 chart: the group on 90.1, 90.2 and 90.3, none on 62.1 or 68.2. 4 printers in
    for 100.00 (25.00 each), 2 sold for 80.00 + VAT 14.40, group «Printerlər»:
      62.1 / 90.1  94.40  (80.00 + 14.40), Kt with the group
      90.3 / 68.2  14.40, Dt with the group
      90.2 / 41.1  50.00  (2 × 25.00), Dt with the group"""
    shop = make_shop(conn, "1c77")
    kind = shop.ledger.add_subconto_kind(shop.company_id, None, "Satış qrupları")
    printers = shop.ledger.add_subconto_value(shop.company_id, kind, "Printerlər")
    for code in ("90.1", "90.2", "90.3"):
        shop.ledger.update_account(shop.company_id, code, subconto=[kind])
    shop.receipt("2026-01-10", "4", "100")
    assert shop.inventory.sale_kinds(shop.company_id) == [kind]
    sale = shop.sale(
        "2026-01-20",
        [SaleLine(shop.item, shop.main, "2", "80", "14.40", sale_subconto=[printers])],
    )
    gl = shop.inventory.load_document(shop.company_id, sale).gl_document_id
    item_value = conn.execute(
        "SELECT subconto_value_id FROM inventory_items WHERE id = ?", (shop.item,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT a.code AS dt, b.code AS kt, p.amount, p.dt_sc1, p.ct_sc1 FROM postings p "
        "JOIN accounts a ON a.id = p.debit_account_id "
        "JOIN accounts b ON b.id = p.credit_account_id "
        "WHERE p.document_id = ? ORDER BY p.line_no",
        (gl,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("62.1", "90.1", 9_440, shop.customer, printers),
        ("90.3", "68.2", 1_440, printers, None),
        ("90.2", "41.1", 5_000, printers, item_value),
    ]


def test_subconto_added_to_46_with_postings_is_optional_there(shop, conn):
    """A sale posted before 46 had a group (70.80 + 29.50, VAT 15.30, cost 36.00). Then the
    group is added: the old postings keep an empty group («<не указано>» in the ОСВ), and a
    receipt dated before the sale reposts it without asking for one. A kind already there
    cannot be changed or removed."""
    shop.receipt("2026-01-10", "10", "120")
    old = shop.sale(
        "2026-01-20",
        [
            SaleLine(shop.item, shop.main, "3", "60", "10.80"),
            SaleLine(None, None, None, "25", "4.50", "Çatdırılma"),
        ],
    )
    kind, (printers,) = sales_groups(shop, "Printerlər")
    other = shop.ledger.add_subconto_kind(shop.company_id, None, "Kanallar")
    with pytest.raises(ValidationError, match="можно только добавить"):
        shop.ledger.update_account(shop.company_id, "46", subconto=[other])
    with pytest.raises(ValidationError, match="можно только добавить"):
        shop.ledger.update_account(shop.company_id, "46", subconto=[])
    shop.ledger.update_account(shop.company_id, "46", subconto=[kind, other])  # free place

    # 5 more printers for 60.00 on Jan 5th: the sale of Jan 20th is posted again;
    # the average becomes (60 + 120) / 15 = 12.00, the cost stays 36.00
    shop.inventory.post_receipt(
        shop.company_id,
        "2026-01-05",
        [ReceiptLine(shop.item, shop.main, "5", "60")],
        shop.acc["60"],
        shop.supplier,
    )
    assert postings_46(shop, conn, old)[-1] == ("46", "41", 3_600, None)

    new = shop.sale(
        "2026-01-25",
        [SaleLine(shop.item, shop.main, "1", "20", "3.60", sale_subconto=[printers])],
    )
    assert postings_46(shop, conn, new)[0] == ("62", "46", 2_360, printers)
    rows = {
        row.name: (row.turnover_dt, row.turnover_ct)
        for row in subconto_balance(conn, shop.company_id, "46", "2026-01-01", "2026-01-31")
    }
    # old: Dt 15.30 + 36.00, Kt 100.30; new: Dt 3.60 + 12.00, Kt 23.60
    assert rows == {"<не указано>": (5_130, 10_030), "Printerlər": (1_560, 2_360)}


def test_late_landed_cost_of_sold_goods_keeps_the_group(shop):
    """10 printers for 100.00, 4 sold in group «Printerlər» (cost 40.00), then delivery
    20.00 on the batch: 12.00 to the stock, 8.00 to 46 — with the sale's group."""
    _, (printers,) = sales_groups(shop, "Printerlər")
    receipt = shop.receipt("2026-01-10", "10", "100")
    receipt_line = shop.inventory.load_document(shop.company_id, receipt).lines[0].id
    shop.sale("2026-01-12", [SaleLine(shop.item, shop.main, "4", "80", sale_subconto=[printers])])
    landed = shop.inventory.post_landed_cost(
        shop.company_id, "2026-01-15", [receipt_line], "20", shop.acc["60"], shop.supplier
    )
    assert postings_46(shop, shop.ledger.conn, landed) == [
        ("41", "60", 1_200, None),
        ("46", "60", 800, printers),
    ]


def test_the_group_is_remembered_by_item_and_by_service(shop, conn):
    """The last sale of the item to the same customer wins; to anyone else, the last one."""
    _, (printers, wholesale, services) = sales_groups(shop, "Printerlər", "Topdan", "Xidmət")
    shop.receipt("2026-01-10", "10", "120")
    shop.sale(
        "2026-01-12",
        [
            SaleLine(shop.item, shop.main, "1", "20", sale_subconto=[wholesale]),
            SaleLine(None, None, None, "5", None, "Çatdırılma", sale_subconto=[services]),
        ],
    )
    beta = shop.ledger.add_subconto_value(
        shop.company_id, shop.ledger.subconto_kind_id(shop.company_id, "counterparty"), "Beta"
    )
    shop.inventory.post_sale(
        shop.company_id,
        "2026-01-15",
        [SaleLine(shop.item, shop.main, "1", "20", sale_subconto=[printers])],
        shop.acc["62"],
        [beta],
    )
    cid = shop.company_id
    assert remembered_sale_subconto(conn, cid, shop.item, "", shop.customer) == (wholesale,)
    assert remembered_sale_subconto(conn, cid, shop.item, "", beta) == (printers,)
    assert remembered_sale_subconto(conn, cid, shop.item) == (printers,)
    assert remembered_sale_subconto(conn, cid, None, "çatdırılma") == (services,)
    assert remembered_sale_subconto(conn, cid, None, "Quraşdırma") == ()


def test_sale_page_asks_for_the_group_and_remembers_it(shop, conn, qtbot):
    """The sale page shows a column «Satış qrupları» (46 has it). A printer sold before in
    group «Printerlər» gets it again by itself; the delivery below, never sold, takes the
    line above's — and is changed to «Xidmətlər» by hand. Posted: 2 printers for 40.00 +
    VAT 7.20 and delivery 10.00 + VAT 1.80, at 12.00 a printer:
      62 / 46   47.20  Printerlər, 62 / 46  11.80  Xidmətlər,
      46 / 68.2  7.20  Printerlər, 46 / 68.2  1.80  Xidmətlər, 46 / 41  24.00  Printerlər"""
    _, (printers, services) = sales_groups(shop, "Printerlər", "Xidmətlər")
    shop.receipt("2026-01-10", "10", "120")
    shop.sale("2026-01-12", [SaleLine(shop.item, shop.main, "1", "20", sale_subconto=[printers])])
    page = sale_page(shop, conn, qtbot)
    model = page.model
    column = model.columns.index(SALE1)
    assert model.headerData(column, Qt.Orientation.Horizontal) == "Satış qrupları"
    assert page._shown(column) and not page._shown(model.columns.index(SALE2))

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    put(0, ITEM, shop.item)
    assert model.rows[0].sale_subconto[0] == printers  # sold in this group before
    put(0, WAREHOUSE, shop.main)
    put(0, QUANTITY, 2 * QUANTITY_FACTOR)
    put(0, AMOUNT, 4_000)
    put(0, SC1, shop.customer)
    model.insert_row()
    put(1, MEMO, "Çatdırılma")
    assert model.rows[1].sale_subconto[0] == printers  # the line above's
    put(1, SALE1, None)
    put(1, AMOUNT, 1_000)
    put(1, SC1, shop.customer)
    assert not page.save(post=True)
    assert "строка 2: заполните субконто «Satış qrupları»" in page.error.text()
    put(1, SALE1, services)

    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert postings_46(shop, conn, page.doc.id) == [
        ("62", "46", 4_720, printers),
        ("62", "46", 1_180, services),
        ("46", "68.2", 720, printers),
        ("46", "68.2", 180, services),
        ("46", "41", 2_400, printers),
    ]
    assert [row.sale_subconto[0] for row in page.model.rows] == [printers, services]
    assert page.model.data(page.model.index(1, column)) == "Xidmətlər"


def test_account_dialog_adds_a_subconto_to_an_account_with_postings(shop, conn, qtbot):
    """46 has postings: the dialog says so, and the free place takes «Satış qrupları»,
    optional on 46 since. The counterparty on 62 stays as it was, not editable."""
    shop.receipt("2026-01-10", "10", "120")
    shop.sale("2026-01-20", [SaleLine(shop.item, shop.main, "1", "20")])
    kind = shop.ledger.add_subconto_kind(shop.company_id, None, "Satış qrupları")
    session = sale_page(shop, conn, qtbot).s
    session.catalog.reload()
    customers = AccountDialog(session, session.catalog.accounts[shop.acc["62"]])
    qtbot.addWidget(customers)
    assert not customers.subconto_hint.isHidden()
    assert [box.isEnabled() for box in customers.subconto] == [False, False, True]

    dialog = AccountDialog(session, session.catalog.accounts[shop.acc["46"]])
    qtbot.addWidget(dialog)
    assert not dialog.subconto_hint.isHidden()
    dialog.subconto[0].setCurrentIndex(dialog.subconto[0].findData(kind))
    dialog.save()
    assert dialog.result() == AccountDialog.DialogCode.Accepted, dialog.error.text()
    session.catalog.reload()
    account = session.catalog.accounts[shop.acc["46"]]
    assert (account.sc_kinds, account.sc_optional) == ((kind, None, None), frozenset({0}))


def test_account_dialog_ticks_a_subconto_that_may_stay_empty(shop, conn, qtbot):
    """62's counterparty ticked «можно не заполнять» in the dialog is optional (D78);
    the tick is shown next time; a position without a kind cannot be ticked."""
    session = sale_page(shop, conn, qtbot).s
    dialog = AccountDialog(session, session.catalog.accounts[shop.acc["62"]])
    qtbot.addWidget(dialog)
    assert [box.isEnabled() for box in dialog.optional] == [True, True, False]  # 62: cp, contract
    dialog.optional[0].setChecked(True)
    dialog.save()
    assert dialog.result() == AccountDialog.DialogCode.Accepted, dialog.error.text()
    session.catalog.reload()
    assert session.catalog.accounts[shop.acc["62"]].sc_optional == frozenset({0})
    again = AccountDialog(session, session.catalog.accounts[shop.acc["62"]])
    qtbot.addWidget(again)
    assert [box.isChecked() for box in again.optional] == [True, False, False]


def test_imported_sale_takes_the_group_the_item_had_last_time(shop, conn):
    """A printer was sold to Alfa in group «Printerlər»; an e-qaimə of 2 printers for 40.00
    to Alfa becomes a draft whose line has that group already."""
    _, (printers,) = sales_groups(shop, "Printerlər")
    shop.ledger.set_subconto_value_tax(shop.company_id, shop.customer, "1234567891")
    shop.receipt("2026-03-01", "10", "120")
    shop.sale("2026-03-02", [SaleLine(shop.item, shop.main, "1", "20", sale_subconto=[printers])])
    row = {
        "id": "s1",
        "serialNumber": "MT2603000333",
        "createdAt": "2026-03-07T10:00:00",
        "kind": "defaultInvoice",
        "receiver": {"tin": "1234567891", "name": "Alfa"},
    }
    detail = {
        **row,
        "items": [
            {
                "productName": "Printer",
                "productGroup": {"code": "8443"},
                "quantity": "2",
                "cost": "40",
                "vat18": "40",
            }
        ],
    }
    plans = plan_import(conn, shop.company_id, [parse_invoice(row, detail, outgoing=True)])
    (draft,) = import_drafts(shop.inventory, shop.company_id, plans)
    (line,) = shop.inventory.load_document(shop.company_id, draft).lines
    assert (line.item_id, line.cost_subconto) == (shop.item, (printers, None, None))
