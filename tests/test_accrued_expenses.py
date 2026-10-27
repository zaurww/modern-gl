"""«Расход за период» in a purchase (D65): a service of September invoiced in October.

The expense is accrued on the last day of September (Dt expense / Kt 76H [supplier]) and
the receipt of October closes the accrual (Dt 76H / Kt 60) instead of debiting the expense;
the supplier's debt and the ƏDV stay on the e-qaimə's date. The numbers are worked out by
hand in each test's docstring."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine
from modern_gl.application.queries import DocumentOwner, document_owner, load_document
from modern_gl.domain.accounts import ACCRUED_EXPENSES
from modern_gl.domain.errors import LedgerError, PeriodClosedError, ValidationError
from modern_gl.reporting.inventory import stock_balances
from modern_gl.reporting.invoices import invoice_report
from tests.helpers.sales import Shop, make_shop


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def cost_item(shop: Shop, name: str) -> int:
    """The cost item named, added the first time it is asked for."""
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    found = shop.ledger.conn.execute(
        "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? AND name = ?",
        (shop.company_id, kind, name),
    ).fetchone()
    return found[0] if found else shop.ledger.add_subconto_value(shop.company_id, kind, name)


def rent(
    shop: Shop,
    amount: str = "500",
    vat: str = "90",
    expense_date: str | None = None,
    memo: str = "Ofisin icarəsi",
    line_id: int | None = None,
) -> ReceiptLine:
    """A purchased service: the office rent, of the month `expense_date` (any day of it)."""
    item = cost_item(shop, "İcarə")
    return ReceiptLine(
        None,
        None,
        None,
        amount,
        memo,
        vat_amount=vat,
        expense_account_id=shop.acc["26"],
        expense_subconto=[item],
        expense_date=expense_date,
        line_id=line_id,
    )


def purchase(shop: Shop, lines: list[ReceiptLine], **kwargs) -> int:
    return shop.inventory.post_receipt(
        shop.company_id,
        "2026-10-05",
        lines,
        shop.acc["60"],
        shop.supplier,
        "Alış",
        vat_rate=STANDARD_VAT_RATE,
        invoice="MT2610000777",
        **kwargs,
    )


def accrual(shop: Shop, receipt: int) -> list[tuple]:
    """(date, Dt code, Kt code, amount, memo) of the receipt's accrual documents, by month."""
    doc = shop.inventory.load_document(shop.company_id, receipt)
    code = {v: k for k, v in shop.acc.items()}
    return [
        (
            r["doc_date"],
            code[r["debit_account_id"]],
            code[r["credit_account_id"]],
            r["amount"],
            r["memo"],
        )
        for a in doc.accruals
        for r in shop.ledger.conn.execute(
            "SELECT d.doc_date, p.* FROM postings p JOIN documents d ON d.id = p.document_id "
            "WHERE d.id = ? ORDER BY p.line_no",
            (a.gl_document_id,),
        )
    ]


def accrual_ids(shop: Shop, receipt: int) -> list[int]:
    return [
        a.gl_document_id for a in shop.inventory.load_document(shop.company_id, receipt).accruals
    ]


def turnover(shop: Shop, code: str, date_from: str, date_to: str) -> tuple[int, int]:
    """(debit, credit) turnover of an account over posted documents in the dates."""
    row = shop.ledger.conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN p.debit_account_id = :a THEN p.amount END), 0), "
        "COALESCE(SUM(CASE WHEN p.credit_account_id = :a THEN p.amount END), 0) "
        "FROM postings p JOIN documents d ON d.id = p.document_id "
        "WHERE d.status = 'posted' AND d.doc_date BETWEEN :f AND :t",
        {"a": shop.acc[code], "f": date_from, "t": date_to},
    ).fetchone()
    return row[0], row[1]


def documents(shop: Shop) -> int:
    return shop.ledger.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]


def test_a_september_service_invoiced_in_october(shop, conn):
    """Rent of September, e-qaimə of 05.10: 500.00 + ƏDV 90.00.
      30.09  Dt 26 [İcarə] / Kt 76H [Təchizatçı]        500.00   — the expense of September
      05.10  Dt 76H [Təchizatçı] / Kt 60 [Təchizatçı]   500.00   — the accrual is closed
      05.10  Dt 19 / Kt 60                                90.00   — ƏDV on the e-qaimə's date
    September: 26 has 500.00, 76H owes 500.00. October: 26 nothing, 76H nil, 60 owes 590.00.
    The e-qaimə report sees 590.00 unpaid (76H is no settlement with the supplier)."""
    receipt = purchase(shop, [rent(shop, expense_date="2026-09-14")])

    doc = shop.inventory.load_document(shop.company_id, receipt)
    assert doc.lines[0].expense_date == "2026-09-30"  # any day names its month
    assert [a.expense_date for a in doc.accruals] == ["2026-09-30"]
    assert accrual(shop, receipt) == [("2026-09-30", "26", "76H", 50_000, "Ofisin icarəsi")]
    assert shop.postings(receipt) == [
        ("76H", "60", 50_000, "Ofisin icarəsi", "MT2610000777"),
        ("19", "60", 9_000, "НДС", "MT2610000777"),
    ]
    supplier = shop.supplier[0]
    sides = conn.execute(
        "SELECT ct_sc1 FROM postings WHERE credit_account_id = :a "
        "UNION ALL SELECT dt_sc1 FROM postings WHERE debit_account_id = :a",
        {"a": shop.acc["76H"]},
    ).fetchall()
    assert [row[0] for row in sides] == [supplier, supplier]

    assert turnover(shop, "26", "2026-09-01", "2026-09-30") == (50_000, 0)
    assert turnover(shop, "76H", "2026-09-01", "2026-09-30") == (0, 50_000)
    assert turnover(shop, "26", "2026-10-01", "2026-10-31") == (0, 0)
    assert turnover(shop, "76H", "2026-10-01", "2026-10-31") == (50_000, 0)
    assert turnover(shop, "60", "2026-10-01", "2026-10-31") == (0, 59_000)

    (row,) = invoice_report(conn, shop.company_id, "2026-10-01", "2026-10-31")
    assert (row.balance, row.vat) == (-59_000, 9_000)

    # the accrual belongs to the receipt: it opens it and is corrected only through it
    accrual_id = doc.accruals[0].gl_document_id
    for gl_id in (doc.gl_document_id, accrual_id):
        owner = document_owner(conn, shop.company_id, gl_id)
        assert owner == DocumentOwner("inventory", receipt, doc.number)
    gl = load_document(conn, shop.company_id, accrual_id)
    assert (gl.inventory_document_id, gl.inventory_number) == (receipt, doc.number)
    assert gl.conversion_id is None and gl.bank_operation_id is None and not gl.editable
    with pytest.raises(ValidationError, match="складским документом"):
        shop.ledger.delete_document(shop.company_id, accrual_id)


def test_only_the_lines_without_an_item_are_accrued(shop, conn):
    """Printers 100.00 + ƏDV 18.00 come to stock on 05.10, as always; rent 500.00 + ƏDV
    90.00 is September's. Accrual: Dt 26 / Kt 76H 500.00 on 30.09. Receipt: Dt 41 / Kt 60
    100.00, Dt 76H / Kt 60 500.00, ƏDV Dt 19 / Kt 60 108.00 = 18.00 + 90.00."""
    receipt = purchase(
        shop,
        [
            ReceiptLine(shop.item, shop.main, "5", "100", vat_amount="18"),
            rent(shop, expense_date="2026-09-30"),
        ],
    )
    assert accrual(shop, receipt) == [("2026-09-30", "26", "76H", 50_000, "Ofisin icarəsi")]
    assert shop.postings(receipt) == [
        ("41", "60", 10_000, "", "MT2610000777"),
        ("76H", "60", 50_000, "Ofisin icarəsi", "MT2610000777"),
        ("19", "60", 10_800, "НДС", "MT2610000777"),
    ]
    (balance,) = stock_balances(conn, shop.company_id)
    assert balance.amount == 10_000


def test_editing_the_receipt_keeps_its_accrual_in_step(shop):
    """Rent corrected to 600.00: the accrual becomes 600.00 and keeps its number. Without
    «Расход за период» the accrual goes away and the rent is October's: Dt 26 / Kt 60.
    Unposting removes the accrual; posting again brings a new one."""
    receipt = purchase(shop, [rent(shop, expense_date="2026-09-30")])
    (first,) = accrual_ids(shop, receipt)

    def edit(amount: str, expense_date: str | None) -> None:
        doc = shop.inventory.load_document(shop.company_id, receipt)
        with shop.inventory.reposting(shop.company_id, receipt):
            shop.inventory.update_receipt_draft(
                shop.company_id,
                receipt,
                "2026-10-05",
                [rent(shop, amount, expense_date=expense_date, line_id=doc.lines[0].id)],
                shop.acc["60"],
                shop.supplier,
                "Alış",
                vat_rate=STANDARD_VAT_RATE,
                invoice="MT2610000777",
            )

    edit("600", "2026-09-30")
    assert accrual_ids(shop, receipt) == [first]
    assert accrual(shop, receipt) == [("2026-09-30", "26", "76H", 60_000, "Ofisin icarəsi")]

    count = documents(shop)
    edit("600", None)
    doc = shop.inventory.load_document(shop.company_id, receipt)
    assert (doc.lines[0].expense_date, doc.accruals) == (None, ())
    assert documents(shop) == count - 1
    assert shop.postings(receipt)[0] == ("26", "60", 60_000, "Ofisin icarəsi", "MT2610000777")

    edit("600", "2026-08-01")  # August now
    assert accrual(shop, receipt)[0][:4] == ("2026-08-31", "26", "76H", 60_000)
    count = documents(shop)
    shop.inventory.unpost_document(shop.company_id, receipt)
    assert shop.inventory.load_document(shop.company_id, receipt).accruals == ()
    assert documents(shop) == count - 2  # the receipt's and the accrual's GL documents
    shop.inventory.post_document(shop.company_id, receipt)
    assert accrual(shop, receipt)[0][:4] == ("2026-08-31", "26", "76H", 60_000)

    shop.inventory.delete_document(shop.company_id, receipt)
    assert documents(shop) == count - 2


def test_the_expense_month_must_be_earlier_and_belong_to_a_service(shop):
    with pytest.raises(
        ValidationError, match="строка 1: расход за октябрь 2026 должен быть раньше"
    ):
        purchase(shop, [rent(shop, expense_date="2026-10-01")])
    with pytest.raises(ValidationError, match=r"строка 1: месяц расхода .* не для товара"):
        purchase(
            shop,
            [
                ReceiptLine(
                    shop.item, shop.main, "5", "100", vat_amount="18", expense_date="2026-09-30"
                )
            ],
        )
    assert documents(shop) == 0  # nothing half-posted


def test_a_closed_month_takes_no_new_accrual_but_keeps_the_one_it_has(shop):
    """September closed: a new accrual there is refused. A receipt accrued before the close
    may still be recalculated if its accrual does not change, but not unposted."""
    receipt = purchase(shop, [rent(shop, expense_date="2026-09-30")])
    shop.ledger.set_closed_through(shop.company_id, "2026-09-30")
    with pytest.raises(PeriodClosedError, match=r"период закрыт по 30\.09\.2026"):
        purchase(shop, [rent(shop, "100", "18", expense_date="2026-09-30")])

    shop.receipt("2026-10-01", "2", "40")  # earlier: the receipt is recalculated after it
    assert accrual(shop, receipt)[0][:4] == ("2026-09-30", "26", "76H", 50_000)
    with pytest.raises(LedgerError, match="период закрыт"):
        shop.inventory.unpost_document(shop.company_id, receipt)
    assert shop.inventory.load_document(shop.company_id, receipt).status == "posted"


def test_a_chart_without_76h_gets_it(shop, conn):
    """A company created before D65 has no accrued expenses account: the first accrual adds
    76H «Начисленные расходы» with the counterparty directory and takes it as the role."""
    shop.ledger.set_account_role(shop.company_id, ACCRUED_EXPENSES, None)
    shop.ledger.delete_account(shop.company_id, "76H")
    receipt = purchase(shop, [rent(shop, expense_date="2026-09-30")])
    account = conn.execute(
        "SELECT a.*, k.code AS kind FROM accounts a "
        "JOIN subconto_kinds k ON k.id = a.sc1_kind_id WHERE a.code = '76H'"
    ).fetchone()
    assert (account["name"], account["account_type"], account["kind"]) == (
        "Начисленные расходы",
        "accrued_expenses",
        "counterparty",
    )
    assert shop.ledger.account_role(shop.company_id, ACCRUED_EXPENSES) == account["id"]
    shop.acc["76H"] = account["id"]
    assert accrual(shop, receipt)[0][:4] == ("2026-09-30", "26", "76H", 50_000)


def test_lines_of_different_months_make_an_accrual_each(shop, conn):
    """Rent of September 500.00 + ƏDV 90.00 and internet of August 100.00 + ƏDV 18.00 on one
    e-qaimə of 05.10, with printers 100.00 + ƏDV 18.00:
      31.08  Dt 26 [İnternet] / Kt 76H   100.00
      30.09  Dt 26 [İcarə] / Kt 76H      500.00
      05.10  Dt 41 / Kt 60 100.00, Dt 76H / Kt 60 500.00, Dt 76H / Kt 60 100.00,
             Dt 19 / Kt 60 126.00 = 18.00 + 90.00 + 18.00
    Two accrual documents. The internet moved to September: one document with both lines,
    the August one gone."""
    internet = rent(shop, "100", "18", expense_date="2026-08-20", memo="İnternet")
    receipt = purchase(
        shop,
        [
            ReceiptLine(shop.item, shop.main, "5", "100", vat_amount="18"),
            rent(shop, expense_date="2026-09-30"),
            internet,
        ],
    )
    doc = shop.inventory.load_document(shop.company_id, receipt)
    assert [a.expense_date for a in doc.accruals] == ["2026-08-31", "2026-09-30"]
    assert accrual(shop, receipt) == [
        ("2026-08-31", "26", "76H", 10_000, "İnternet"),
        ("2026-09-30", "26", "76H", 50_000, "Ofisin icarəsi"),
    ]
    assert [p[:3] for p in shop.postings(receipt)] == [
        ("41", "60", 10_000),
        ("76H", "60", 50_000),
        ("76H", "60", 10_000),
        ("19", "60", 12_600),
    ]
    assert turnover(shop, "26", "2026-08-01", "2026-08-31") == (10_000, 0)
    assert turnover(shop, "26", "2026-09-01", "2026-09-30") == (50_000, 0)
    assert turnover(shop, "76H", "2026-10-01", "2026-10-31") == (60_000, 0)
    for a in doc.accruals:
        assert document_owner(conn, shop.company_id, a.gl_document_id) == DocumentOwner(
            "inventory", receipt, doc.number
        )

    count = documents(shop)
    september = accrual_ids(shop, receipt)[1]
    lines = doc.lines
    with shop.inventory.reposting(shop.company_id, receipt):
        shop.inventory.update_receipt_draft(
            shop.company_id,
            receipt,
            "2026-10-05",
            [
                ReceiptLine(shop.item, shop.main, "5", "100", vat_amount="18", line_id=lines[0].id),
                rent(shop, expense_date="2026-09-30", line_id=lines[1].id),
                rent(shop, "100", "18", "2026-09-01", "İnternet", lines[2].id),
            ],
            shop.acc["60"],
            shop.supplier,
            "Alış",
            vat_rate=STANDARD_VAT_RATE,
            invoice="MT2610000777",
        )
    assert accrual_ids(shop, receipt) == [september]  # September's keeps its number
    assert accrual(shop, receipt) == [
        ("2026-09-30", "26", "76H", 50_000, "Ofisin icarəsi"),
        ("2026-09-30", "26", "76H", 10_000, "İnternet"),
    ]
    assert documents(shop) == count - 1


def receipt_page(shop: Shop, conn, qtbot, day: date):
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session
    from modern_gl.desktop.widgets import to_qdate

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    page = InventoryDocumentPage(session, doc_type="receipt")
    qtbot.addWidget(page)
    page.date.setDate(to_qdate(day))
    return page


def repair_line(shop: Shop, page, row: int = 0, amount: int = 5_000) -> None:
    """A service «Təmir» on the row: 26 [Təmir] / 60 [supplier], `amount` kopecks."""
    from modern_gl.desktop.inventory_document_page import ACCOUNT, AMOUNT, ESC1, EXPENSE, SC1

    page._make_service(row, "Təmir")
    model = page.model
    for key, value in ((EXPENSE, shop.acc["26"]), (AMOUNT, amount), (ACCOUNT, shop.acc["60"])):
        assert model.setData(model.index(row, model.columns.index(key)), value)
    assert model.setData(model.index(row, model.columns.index(SC1)), shop.supplier[0])
    repair = cost_item(shop, "Təmir")
    page.s.catalog.reload()
    assert model.setData(model.index(row, model.columns.index(ESC1)), repair)


def test_receipt_page_takes_the_month_on_the_line(shop, conn, qtbot):
    """The column «Расход за» appears with a service line; its list is the twelve months
    before the document's and «несколько месяцев…». Repair of September 50.00 + ƏDV 9.00
    on 05.10: Dt 26 / Kt 76H 50.00 on 30.09, the receipt Dt 76H / Kt 60 50.00 and
    Dt 19 / Kt 60 9.00."""
    from modern_gl.desktop.inventory_document_page import EXPENSE_MONTH
    from modern_gl.desktop.inventory_document_page.columns import SEVERAL_MONTHS

    page = receipt_page(shop, conn, qtbot, date(2026, 10, 5))
    model = page.model
    column = model.columns.index(EXPENSE_MONTH)
    assert page.table.isColumnHidden(column)  # goods only so far
    repair_line(shop, page)
    assert not page.table.isColumnHidden(column)
    choices = model.choices(0, EXPENSE_MONTH)
    assert choices[:2] == [(202609, "сентябрь 2026"), (202608, "август 2026")]
    assert (len(choices), choices[-2][0], choices[-1][0]) == (13, 202510, SEVERAL_MONTHS)
    assert model.month_code_of("09.2026") == 202609 == model.month_code_of("сент")
    assert model.month_code_of("2025-10") == 202510
    with pytest.raises(ValueError, match="месяц не распознан"):
        model.month_code_of("13.2026")

    assert model.setData(model.index(0, column), 202609)
    assert model.data(model.index(0, column)) == "сентябрь 2026"
    assert model.rows[0].expense_date == "2026-09-30"
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert [line.expense_date for line in page.doc.lines] == ["2026-09-30"]
    assert accrual(shop, page.doc.id) == [("2026-09-30", "26", "76H", 5_000, "Təmir")]
    assert [p[:3] for p in shop.postings(page.doc.id)] == [("76H", "60", 5_000), ("19", "60", 900)]
    assert page.model.rows[0].expense_date == "2026-09-30"  # loaded back
    assert not page.btn_accrual.isHidden()


def test_a_line_spread_over_months_is_divided_evenly(shop, conn, qtbot, monkeypatch):
    """Insurance 300.01 + ƏDV 54.00 for July–September on the e-qaimə of 05.10, spread over
    the three months: 100.00 / 100.00 / 100.01 (the kopeck goes to the last month),
    ƏDV 18.00 each. Posted: Dt 26 / Kt 76H 100.00 on 31.07 and 31.08, 100.01 on 30.09."""
    from PySide6.QtCore import QPersistentModelIndex
    from PySide6.QtWidgets import QDialog

    from modern_gl.desktop.inventory_document_page import EXPENSE_MONTH, VAT, splits

    page = receipt_page(shop, conn, qtbot, date(2026, 10, 5))
    model = page.model
    repair_line(shop, page, amount=30_001)
    assert model.setData(model.index(0, model.columns.index(VAT)), 5_400)
    monkeypatch.setattr(splits.MonthRangeDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        splits.MonthRangeDialog,
        "months",
        lambda self: ["2026-07-31", "2026-08-31", "2026-09-30"],
    )
    page._split_months(QPersistentModelIndex(model.index(0, model.columns.index(EXPENSE_MONTH))))
    assert [(r.amount, r.vat_amount, r.expense_date, r.quantity) for r in model.rows] == [
        (10_000, 1_800, "2026-07-31", None),
        (10_000, 1_800, "2026-08-31", None),
        (10_001, 1_800, "2026-09-30", None),
    ]
    assert model.total() == 30_001 and model.vat_total() == 5_400
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    assert accrual(shop, page.doc.id) == [
        ("2026-07-31", "26", "76H", 10_000, "Təmir"),
        ("2026-08-31", "26", "76H", 10_000, "Təmir"),
        ("2026-09-30", "26", "76H", 10_001, "Təmir"),
    ]
    assert [p[:3] for p in shop.postings(page.doc.id)] == [
        ("76H", "60", 10_000),
        ("76H", "60", 10_000),
        ("76H", "60", 10_001),
        ("19", "60", 5_400),
    ]
    assert len(page.doc.accruals) == 3 and not page.btn_accrual.isHidden()


def test_the_month_range_dialog_lists_the_months_between_its_ends(shop, conn, qtbot):
    """From August to October 2026 for a document of November: three months, earliest
    first, whichever end is picked first; a single month is refused by the split."""
    from PySide6.QtWidgets import QWidget

    from modern_gl.desktop.inventory_document_page.splits import MonthRangeDialog

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = MonthRangeDialog(parent, "2026-11-12")
    assert dialog.first.currentData() == "2026-09-30" and dialog.last.currentData() == "2026-10-31"
    dialog.first.setCurrentIndex(dialog.first.findData("2026-10-31"))
    dialog.last.setCurrentIndex(dialog.last.findData("2026-08-31"))
    assert dialog.months() == ["2026-08-31", "2026-09-30", "2026-10-31"]
    dialog.last.setCurrentIndex(dialog.last.findData("2026-10-31"))
    assert dialog.months() == ["2026-10-31"]
    page = receipt_page(shop, conn, qtbot, date(2026, 11, 12))
    repair_line(shop, page)
    with pytest.raises(ValidationError, match="хотя бы два месяца"):
        page.model.split_by_months(0, ["2026-10-31"])


def test_picking_several_months_in_the_cell_asks_the_page(shop, conn, qtbot, monkeypatch):
    """«несколько месяцев…» typed into the cell commits nothing: the delegate tells the
    page, which asks for the months (the question itself is kept out of the test)."""
    from PySide6.QtWidgets import QLineEdit

    from modern_gl.desktop.inventory_document_page import EXPENSE_MONTH

    page = receipt_page(shop, conn, qtbot, date(2026, 10, 5))
    repair_line(shop, page)
    asked = []
    monkeypatch.setattr(page, "_split_months", lambda index: asked.append(index.row()))
    editor = QLineEdit("несколько")
    index = page.model.index(0, page.model.columns.index(EXPENSE_MONTH))
    page.delegate.setModelData(editor, page.model, index)
    qtbot.waitUntil(lambda: asked == [0])  # deferred until the cell editor is closed
    assert page.model.rows[0].expense_date is None
    editor.setText("август 2026")
    page.delegate.setModelData(editor, page.model, index)
    assert page.model.rows[0].expense_date == "2026-08-31"
    editor.setText("")
    page.delegate.setModelData(editor, page.model, index)
    assert page.model.rows[0].expense_date is None


def test_the_accrual_is_not_a_landed_cost_source(shop):
    """The accrual document is the warehouse's own (D65): the list of sources leaves it out,
    and posting a landed cost refuses it the same way."""
    from modern_gl.application.inventory import LandedCostCharge, LandedCostTarget
    from modern_gl.reporting.inventory import cost_sources

    receipt = purchase(shop, [rent(shop, expense_date="2026-09-30")])
    (accrual_doc,) = accrual_ids(shop, receipt)
    assert accrual_doc not in {
        s.document_id for s in cost_sources(shop.ledger.conn, shop.company_id)
    }

    goods = shop.receipt("2026-10-06", "10", "100")
    line = shop.inventory.load_document(shop.company_id, goods).lines[0].id
    with pytest.raises(ValidationError, match="складского документа"):
        shop.inventory.create_landed_cost_draft(
            shop.company_id,
            "2026-10-07",
            [LandedCostTarget(line)],
            [LandedCostCharge("10", source_document_id=accrual_doc, source_line_no=1)],
            "value",
            "Партия",
        )
