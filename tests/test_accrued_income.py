"""«Доход за» in a sale (D65 for sales): a service of September invoiced in October.

The income is accrued on the last day of September (Dt 76G [customer] / Kt revenue) and
the sale of October closes the accrual (Dt 62 / Kt 76G) instead of crediting the revenue;
the customer's debt and the ƏDV stay on the e-qaimə's date. The numbers are worked out by
hand in each test's docstring."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.inventory import SaleLine
from modern_gl.application.queries import DocumentOwner, document_owner, load_document
from modern_gl.domain.accounts import SALES_VAT
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.invoices import invoice_report
from modern_gl.reporting.profit_loss import profit_and_loss
from tests.helpers.accruals import accrual, accrual_ids, documents, turnover
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def consulting(
    amount: str = "500",
    vat: str = "90",
    expense_date: str | None = None,
    memo: str = "Konsaltinq",
    line_id: int | None = None,
) -> SaleLine:
    """A sold service, of the month `expense_date` (any day of it)."""
    return SaleLine(None, None, None, amount, vat, memo, line_id=line_id, expense_date=expense_date)


def sale(shop: Shop, lines: list[SaleLine], **kwargs) -> int:
    return shop.sale("2026-10-05", lines, invoice="MT2610000555", **kwargs)


def revenue(shop: Shop, date_from: str, date_to: str) -> int:
    statement = profit_and_loss(shop.ledger.conn, shop.company_id, date_from, date_to)
    (line,) = [ln for ln in statement.lines if ln.title == "Выручка"]
    return line.amount[0]


def test_a_september_service_invoiced_in_october(shop, conn):
    """Consulting of September, e-qaimə of 05.10: 500.00 + ƏDV 90.00. The classic chart
    charges the ƏDV from 46 (Dt 62 / Kt 46 with ƏDV, Dt 46 / Kt 68.2), so:
      30.09  Dt 76G [Alfa] / Kt 46                 500.00   — the income of September
      05.10  Dt 62 [Alfa] / Kt 76G [Alfa]          500.00   — the accrual is closed
      05.10  Dt 46 / Kt 68.2                        90.00   — ƏDV on the e-qaimə's date
      05.10  Dt 62 [Alfa] / Kt 46                   90.00   — the ƏDV's part of the revenue
    September: revenue 500.00, 76G owed 500.00. October: 46 nets to nil, 76G nil, 62 owes
    590.00. The e-qaimə report sees 590.00 unpaid (76G is no settlement with the customer)."""
    doc_id = sale(shop, [consulting(expense_date="2026-09-14")])

    doc = shop.inventory.load_document(shop.company_id, doc_id)
    assert doc.lines[0].expense_date == "2026-09-30"  # any day names its month
    assert [a.expense_date for a in doc.accruals] == ["2026-09-30"]
    assert accrual(shop, doc_id) == [("2026-09-30", "76G", "46", 50_000, "Konsaltinq")]
    assert shop.postings(doc_id) == [
        ("62", "76G", 50_000, "Konsaltinq", "MT2610000555"),
        ("46", "68.2", 9_000, "НДС", "MT2610000555"),
        ("62", "46", 9_000, "Konsaltinq", "MT2610000555"),
    ]
    sides = conn.execute(
        "SELECT dt_sc1 FROM postings WHERE debit_account_id = :a "
        "UNION ALL SELECT ct_sc1 FROM postings WHERE credit_account_id = :a",
        {"a": shop.acc["76G"]},
    ).fetchall()
    assert [row[0] for row in sides] == [shop.customer, shop.customer]

    assert turnover(shop, "46", "2026-09-01", "2026-09-30") == (0, 50_000)
    assert turnover(shop, "76G", "2026-09-01", "2026-09-30") == (50_000, 0)
    assert turnover(shop, "46", "2026-10-01", "2026-10-31") == (9_000, 9_000)
    assert turnover(shop, "76G", "2026-10-01", "2026-10-31") == (0, 50_000)
    assert turnover(shop, "62", "2026-10-01", "2026-10-31") == (59_000, 0)
    assert revenue(shop, "2026-09-01", "2026-09-30") == 50_000
    assert revenue(shop, "2026-10-01", "2026-10-31") == 0

    (row,) = invoice_report(conn, shop.company_id, "2026-10-01", "2026-10-31")
    assert (row.balance, row.vat) == (59_000, 9_000)

    # the accrual belongs to the sale: it opens it and is corrected only through it
    accrual_id = doc.accruals[0].gl_document_id
    for gl_id in (doc.gl_document_id, accrual_id):
        owner = document_owner(conn, shop.company_id, gl_id)
        assert owner == DocumentOwner("inventory", doc_id, doc.number)
    gl = load_document(conn, shop.company_id, accrual_id)
    assert (gl.inventory_document_id, gl.inventory_number) == (doc_id, doc.number)
    assert gl.memo == f"Начисление дохода по продаже №{doc.number}"
    with pytest.raises(ValidationError, match="складским документом"):
        shop.ledger.delete_document(shop.company_id, accrual_id)


def test_the_1c77_chart_accrues_to_its_revenue_account(conn):
    """The same in the 1C 7.7 chart (62.1 / 90.1 with ƏDV, 90.3 / 68.2): the accrual
    Dt 76G / Kt 90.1 500.00 on 30.09; the sale 62.1 / 76G 500.00, 90.3 / 68.2 90.00 and
    62.1 / 90.1 90.00 on 05.10."""
    shop = make_shop(conn, "1c77")
    doc_id = sale(shop, [consulting(expense_date="2026-09-30")])
    assert accrual(shop, doc_id) == [("2026-09-30", "76G", "90.1", 50_000, "Konsaltinq")]
    assert [p[:3] for p in shop.postings(doc_id)] == [
        ("62.1", "76G", 50_000),
        ("90.3", "68.2", 9_000),
        ("62.1", "90.1", 9_000),
    ]


def test_without_a_vat_charge_account_the_revenue_posting_is_the_net(shop):
    """No «НДС начисляется со счёта»: the revenue posting is without ƏDV, so the sale
    closes the accrual whole and charges the ƏDV from the customer: Dt 62 / Kt 76G 500.00,
    Dt 62 / Kt 68.2 90.00; no third posting."""
    shop.ledger.set_account_role(shop.company_id, SALES_VAT, None)
    doc_id = sale(shop, [consulting(expense_date="2026-09-30")])
    assert accrual(shop, doc_id) == [("2026-09-30", "76G", "46", 50_000, "Konsaltinq")]
    assert [p[:3] for p in shop.postings(doc_id)] == [
        ("62", "76G", 50_000),
        ("62", "68.2", 9_000),
    ]


def test_only_the_services_are_accrued(shop, conn):
    """Printers leave stock on 05.10, as always: 3 for 60.00 + ƏDV 10.80; the consulting
    is September's. Accrual: Dt 76G / Kt 46 500.00 on 30.09. Sale: Dt 62 / Kt 46 70.80,
    Dt 62 / Kt 76G 500.00, ƏDV Dt 46 / Kt 68.2 100.80, Dt 46 / Kt 41 36.00 the cost,
    Dt 62 / Kt 46 90.00 the ƏDV's part of the consulting."""
    shop.receipt("2026-01-10", "10", "120")
    doc_id = sale(
        shop,
        [
            SaleLine(shop.item, shop.main, "3", "60", "10.80"),
            consulting(expense_date="2026-09-30"),
        ],
    )
    assert accrual(shop, doc_id) == [("2026-09-30", "76G", "46", 50_000, "Konsaltinq")]
    assert [p[:3] for p in shop.postings(doc_id)] == [
        ("62", "46", 7_080),
        ("62", "76G", 50_000),
        ("46", "68.2", 10_080),
        ("46", "41", 3_600),
        ("62", "46", 9_000),
    ]


def test_the_month_must_be_earlier_and_belong_to_a_service(shop):
    with pytest.raises(ValidationError, match="доход за октябрь 2026 должен быть раньше"):
        sale(shop, [consulting(expense_date="2026-10-01")])
    shop.receipt("2026-01-10", "10", "120")
    with pytest.raises(ValidationError, match="месяц дохода указывается для услуг"):
        sale(shop, [SaleLine(shop.item, shop.main, "3", "60", "10.80", expense_date="2026-09-30")])


def test_editing_the_sale_keeps_its_accrual_in_step(shop):
    """Consulting corrected to 600.00: the accrual becomes 600.00 and keeps its number.
    Without «Доход за» the accrual goes away and the income is October's: Dt 62 / Kt 46.
    Unposting removes the accrual; deleting the sale, too."""
    doc_id = sale(shop, [consulting(expense_date="2026-09-30")])
    (first,) = accrual_ids(shop, doc_id)

    def edit(amount: str, expense_date: str | None) -> None:
        doc = shop.inventory.load_document(shop.company_id, doc_id)
        with shop.inventory.reposting(shop.company_id, doc_id):
            shop.inventory.update_sale_draft(
                shop.company_id,
                doc_id,
                "2026-10-05",
                [consulting(amount, "0", expense_date, line_id=doc.lines[0].id)],
                shop.acc["62"],
                [shop.customer, shop.contract],
                vat_rate=None,
                invoice="MT2610000555",
            )

    edit("600", "2026-09-30")
    assert accrual_ids(shop, doc_id) == [first]
    assert accrual(shop, doc_id) == [("2026-09-30", "76G", "46", 60_000, "Konsaltinq")]
    assert [p[:3] for p in shop.postings(doc_id)] == [("62", "76G", 60_000)]

    count = documents(shop)
    edit("600", None)
    assert accrual_ids(shop, doc_id) == []
    assert [p[:3] for p in shop.postings(doc_id)] == [("62", "46", 60_000)]
    assert documents(shop) == count - 1

    edit("600", "2026-08-15")
    assert [a.expense_date for a in accrual_ids_dates(shop, doc_id)] == ["2026-08-31"]
    shop.inventory.unpost_document(shop.company_id, doc_id)
    assert accrual_ids(shop, doc_id) == []
    shop.inventory.post_document(shop.company_id, doc_id)
    assert accrual(shop, doc_id) == [("2026-08-31", "76G", "46", 60_000, "Konsaltinq")]
    shop.inventory.delete_document(shop.company_id, doc_id)
    assert documents(shop) == count - 2


def accrual_ids_dates(shop: Shop, doc_id: int):
    return shop.inventory.load_document(shop.company_id, doc_id).accruals


def sale_page(shop: Shop, conn, qtbot, day: date):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session
    from modern_gl.desktop.widgets import to_qdate

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="sale")
    qtbot.addWidget(page)
    page.date.setDate(to_qdate(day))
    return page


def test_sale_page_takes_the_month_on_the_line(shop, conn, qtbot):
    """The column «Доход за» is the last of a sale; it appears with a service line and
    offers the twelve months before the document's. Consulting of September 500.00 +
    ƏDV 90.00 sold on 05.10 from the page: the accrual Dt 76G / Kt 46 500.00 on 30.09."""
    from PySide6.QtCore import Qt

    from modern_gl.desktop.inventory_document_page import AMOUNT, EXPENSE_MONTH, MEMO, SC1, SC2

    page = sale_page(shop, conn, qtbot, date(2026, 10, 5))
    model = page.model
    column = model.columns.index(EXPENSE_MONTH)
    assert column == len(model.columns) - 1
    assert model.headerData(column, Qt.Orientation.Horizontal) == "Доход за"
    assert page.btn_accrual.toolTip() == "Проводки начисления дохода в месяце услуги"
    assert page.table.isColumnHidden(column)  # goods only so far

    def put(row: int, key: str, value) -> None:
        assert model.setData(model.index(row, model.columns.index(key)), value)

    put(0, MEMO, "Konsaltinq")
    put(0, AMOUNT, 50_000)
    put(0, SC1, shop.customer)
    put(0, SC2, shop.contract)
    assert model.rows[0].vat_amount == 9_000
    assert not page.table.isColumnHidden(column)
    choices = model.choices(0, EXPENSE_MONTH)
    assert choices[:2] == [(202609, "сентябрь 2026"), (202608, "август 2026")]
    put(0, EXPENSE_MONTH, 202609)
    assert model.data(model.index(0, column)) == "сентябрь 2026"
    assert model.rows[0].expense_date == "2026-09-30"
    page.invoice.setText("MT2610000555")

    assert page.save(post=True), page.error.text()
    assert page.doc is not None and page.doc.status == "posted"
    assert accrual(shop, page.doc.id) == [("2026-09-30", "76G", "46", 50_000, "Konsaltinq")]
    assert [p[:3] for p in shop.postings(page.doc.id)] == [
        ("62", "76G", 50_000),
        ("46", "68.2", 9_000),
        ("62", "46", 9_000),
    ]
    assert page.btn_accrual.isVisible() or page.btn_accrual.isVisibleTo(page)
