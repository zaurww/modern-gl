"""E-qaimə: the invoice number of a posting, the report per invoice, the subconto
balance in each currency. Figures are worked out by hand in the comments."""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import load_document
from modern_gl.application.quick_entry import parse
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.infrastructure.chart_csv import apply_chart_template
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.invoices import invoice_report
from modern_gl.reporting.reports import account_card, subconto_balance


@pytest.fixture
def firm():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    kind = {c: ledger.subconto_kind_id(cid, c) for c in ("counterparty", "contract")}
    v = {
        "Альфа": ledger.add_subconto_value(cid, kind["counterparty"], "Альфа"),
        "Бета": ledger.add_subconto_value(cid, kind["counterparty"], "Бета"),
        "Аренда": ledger.add_subconto_value(
            cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"
        ),
        "Kapital": ledger.add_subconto_value(
            cid, ledger.subconto_kind_id(cid, "bank_account"), "Kapital"
        ),
    }
    v["Д-1"] = ledger.add_subconto_value(cid, kind["contract"], "Д-1", owner_id=v["Альфа"])
    v["Общий"] = ledger.add_subconto_value(cid, kind["contract"], "Общий")
    ledger.set_subconto_value_tax(cid, v["Альфа"], "1234567890")
    cat = Catalog(conn, cid)
    acc = {code: a.id for code, a in cat.by_code.items()}
    yield conn, ledger, cid, acc, v
    conn.close()


def test_number_is_written_as_the_portal_shows_it():
    assert normalize_invoice(" mt 2410 001 ") == "MT2410001"
    assert normalize_invoice("№MT2410001") == "MT2410001"
    assert normalize_invoice("  ") is None
    with pytest.raises(ValidationError, match="e-qaimə"):
        normalize_invoice("X" * 41)


def purchase_sale_payment(ledger: Ledger, cid: int, acc: dict, v: dict) -> dict[str, int]:
    alfa, beta = (v["Альфа"], v["Д-1"]), (v["Бета"], v["Общий"])
    rent = (v["Аренда"],)
    docs = {}
    # February: rent from Alfa 400, not paid
    docs["feb"] = ledger.post_new(
        cid,
        "2026-02-10",
        [PostingInput(acc["26"], acc["60"], "400", rent, alfa, invoice="MT2402005")],
    )
    # March 5: services from Alfa 1 000 + ƏDV 180 on one e-qaimə (typed in lower case)
    docs["buy"] = ledger.post_new(
        cid,
        "2026-03-05",
        [
            PostingInput(acc["26"], acc["60"], "1000", rent, alfa, invoice="mt 2410 001"),
            PostingInput(acc["19"], acc["60"], "180", (v["Альфа"],), alfa, invoice="MT2410001"),
        ],
    )
    # March 10: sale to Beta 1 180, of which ƏDV 180
    docs["sell"] = ledger.post_new(
        cid,
        "2026-03-10",
        [
            PostingInput(acc["62"], acc["46"], "1180", beta, (), invoice="MT2410777"),
            PostingInput(acc["46"], acc["68.2"], "180", (), (), invoice="MT2410777"),
        ],
    )
    # March 20: 500 paid to Alfa for the March invoice
    docs["pay"] = ledger.post_new(
        cid,
        "2026-03-20",
        [PostingInput(acc["60"], acc["51"], "500", alfa, (v["Kapital"],), invoice="MT2410001")],
    )
    return docs


def test_report_gathers_each_invoice(firm):
    conn, ledger, cid, acc, v = firm
    docs = purchase_sale_payment(ledger, cid, acc, v)
    rows = {r.invoice: r for r in invoice_report(conn, cid, "2026-03-01", "2026-03-31")}
    assert set(rows) == {"MT2410001", "MT2410777"}  # February's has no March posting

    bought = rows["MT2410001"]
    # Kt 60: 1 000 + 180 = 1 180; Dt 60: 500 paid; ƏDV: the 19 line, 180
    assert (bought.credit, bought.debit, bought.vat) == (118_000, 50_000, 18_000)
    assert bought.balance == -68_000  # 1 180 - 500 = 680 still owed (Kt)
    assert (bought.counterparties, bought.contract_id) == ([v["Альфа"]], v["Д-1"])
    assert bought.doc_date == "2026-03-05"
    assert [d for d, _ in bought.documents] == [docs["buy"], docs["pay"]]

    sold = rows["MT2410777"]
    # Dt 62: 1 180 (46 is not a settlement); ƏDV: the 46 / 68.2 line, 180
    assert (sold.debit, sold.credit, sold.vat, sold.balance) == (118_000, 0, 18_000, 118_000)
    assert sold.counterparties == [v["Бета"]]


def test_open_only_shows_unpaid_of_any_date(firm):
    conn, ledger, cid, acc, v = firm
    purchase_sale_payment(ledger, cid, acc, v)
    rows = invoice_report(conn, cid, "2026-03-01", "2026-03-31", open_only=True)
    # February's 400, March's 680 owed to Alfa, Beta's 1 180
    assert {r.invoice: r.balance for r in rows} == {
        "MT2402005": -40_000,
        "MT2410001": -68_000,
        "MT2410777": 118_000,
    }


def test_storno_keeps_the_number_and_cancels_it_out(firm):
    conn, ledger, cid, acc, v = firm
    docs = purchase_sale_payment(ledger, cid, acc, v)
    ledger.reverse(cid, docs["pay"], "2026-03-25")
    rows = {r.invoice: r for r in invoice_report(conn, cid, "2026-03-01", "2026-03-31")}
    assert rows["MT2410001"].balance == -118_000  # 500 paid, then reversed: 1 180 owed
    assert [p.invoice for p in load_document(conn, cid, docs["pay"]).postings] == ["MT2410001"]


def test_one_number_with_two_counterparties_is_noticed(firm):
    conn, ledger, cid, acc, v = firm
    for partner, contract in (("Альфа", "Д-1"), ("Бета", "Общий")):
        ledger.post_new(
            cid,
            "2026-03-05",
            [
                PostingInput(
                    acc["26"],
                    acc["60"],
                    "100",
                    (v["Аренда"],),
                    (v[partner], v[contract]),
                    invoice="MT1",
                )
            ],
        )
    (row,) = invoice_report(conn, cid, "2026-03-01", "2026-03-31")
    assert row.counterparties == [v["Альфа"], v["Бета"]] and row.credit == 20_000


def test_card_shows_the_number(firm):
    conn, ledger, cid, acc, v = firm
    purchase_sale_payment(ledger, cid, acc, v)
    card = account_card(conn, cid, "60", "2026-03-01", "2026-03-31")
    assert [ln.invoice for ln in card.lines] == ["MT2410001", "MT2410001", "MT2410001"]


def test_quick_entry_takes_the_number_after_the_amount(firm):
    conn, _, cid, _, _ = firm
    entry = parse("26 аренда / 60 альфа, д-1 1000 №mt2410001 Аренда за март", Catalog(conn, cid))
    (line,) = entry.lines
    assert (line.invoice, line.memo, line.amount) == ("MT2410001", "Аренда за март", 100_000)


def test_subconto_balance_in_each_currency(firm):
    """A foreign supplier: one invoice in USD, another in EUR."""
    conn, ledger, cid, acc, v = firm
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.set_rate(cid, "EUR", "2026-03-01", parse_rate("2"))
    usd, eur = ledger.currency_id(cid, "USD"), ledger.currency_id(cid, "EUR")
    acme = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "counterparty"), "Acme")
    rent, partner = (v["Аренда"],), (acme, v["Общий"])
    ledger.post_new(
        cid,
        "2026-03-05",
        [
            # 1 000 USD × 1.7 = 1 700 ₼;  500 EUR × 2 = 1 000 ₼
            PostingInput(acc["26"], acc["60"], "1700", rent, partner, "", usd, "1000"),
            PostingInput(acc["26"], acc["60"], "1000", rent, partner, "", eur, "500"),
        ],
    )
    (row,) = [r for r in subconto_balance(conn, cid, "60", "2026-03-01", "2026-03-31")]
    assert row.closing_ct == 270_000
    assert row.currency_closing == {"USD": -100_000, "EUR": -50_000}


def test_grid_column_only_on_settlement_and_vat_lines(firm, qtbot):
    from modern_gl.desktop.postings import INVOICE, PostingRow, PostingsModel

    conn, _, cid, acc, _ = firm
    cat = Catalog(conn, cid)
    model = PostingsModel(
        cat,
        [
            PostingRow(debit=acc["26"], credit=acc["60"], amount=100, invoice="MT1"),
            PostingRow(debit=acc["50"], credit=acc["51"], amount=100, invoice="MT2"),
            PostingRow(debit=acc["46"], credit=acc["68.2"], amount=100),
        ],
    )
    assert [model.applies(r, INVOICE) for r in range(3)] == [True, False, True]
    assert model.parse(2, INVOICE, " mt 77 ") == "MT77"
    # a number left on a line that no longer takes one is not saved
    assert [p.invoice for p in model.to_inputs()] == ["MT1", "", ""]


def test_invoice_number_fills_related_postings_without_overwriting(firm):
    from modern_gl.desktop.postings import INVOICE, PostingRow, PostingsModel

    conn, _, cid, acc, v = firm
    cat = Catalog(conn, cid)
    alfa = [v["Альфа"], v["Д-1"]]
    model = PostingsModel(
        cat,
        [
            PostingRow(acc["26"], [v["Аренда"], None, None], acc["60"], alfa),
            PostingRow(acc["19"], [v["Альфа"], None, None], acc["60"], alfa),
        ],
    )

    model.setData(model.index(0, INVOICE), model.parse(0, INVOICE, " mt 77 "))
    assert [row.invoice for row in model.rows] == ["MT77", "MT77"]

    # Qt asks for the account text whenever it repaints the table.  Reading display
    # data must not erase a number that has just been inherited by the related row.
    assert model.index(1, 4).data() == "60"
    assert [row.invoice for row in model.rows] == ["MT77", "MT77"]

    model.setData(model.index(1, INVOICE), "OTHER")
    model.setData(model.index(0, INVOICE), "MT88")
    assert [row.invoice for row in model.rows] == ["MT88", "OTHER"]


def test_page_finds_an_invoice_by_vöen(firm, qtbot):
    from PySide6.QtWidgets import QApplication

    from modern_gl.desktop import theme
    from modern_gl.desktop.invoices_page import InvoicesPage
    from modern_gl.desktop.reports_page import ReportParams
    from modern_gl.desktop.session import Session

    conn, ledger, cid, acc, v = firm
    purchase_sale_payment(ledger, cid, acc, v)
    theme.apply(QApplication.instance())
    s = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _m: None)
    page = InvoicesPage(s, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    assert [r.invoice for r in page.model.rows] == ["MT2410001", "MT2410777"]
    page.search.setText("1234567890")  # Alfa's VÖEN
    assert [r.invoice for r in page.model.rows] == ["MT2410001"]
    assert page.model.index(0, 8).data() == "680.00 Кт"
    opened: list[int] = []
    page.open_document.connect(opened.append)
    page.drill(page.model.rows[0])
    assert opened == [page.model.rows[0].documents[0][0]]


def test_warehouse_receipt_carries_its_e_qaime_or_declaration(firm):
    from modern_gl.application.inventory import Inventory, ReceiptLine
    from modern_gl.domain.invoice import CUSTOMS

    conn, _, cid, acc, v = firm
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "шт", "Штука", precision=0)
    item = inventory.add_item(cid, "Бумага", unit, acc["41"])
    store = inventory.add_warehouse(cid, "Склад")
    alfa = (v["Альфа"], v["Д-1"])
    # local supplier: 10 × 10.00 = 100.00 + ƏDV 18.00 on e-qaimə MT55
    local = inventory.post_receipt(
        cid,
        "2026-03-05",
        [ReceiptLine(item, store, "10", "100", vat_amount="18")],
        acc["60"],
        alfa,
        "Поступление",
        invoice="mt 55",
    )
    # imported goods: 300.00 by customs declaration, no ƏDV in the receipt
    imported = inventory.post_receipt(
        cid,
        "2026-03-06",
        [ReceiptLine(item, store, "5", "300")],
        acc["60"],
        (v["Бета"], v["Общий"]),
        "Импорт",
        invoice="AZ1000/060326/0001234",
        invoice_kind=CUSTOMS,
    )
    doc = inventory.load_document(cid, local)
    assert (doc.invoice, doc.invoice_kind) == ("MT55", "")
    gl = load_document(conn, cid, doc.gl_document_id or 0)
    # Dt 41 / Kt 60 100.00 and Dt 19 / Kt 60 18.00, both on MT55
    assert [(p.amount, p.invoice) for p in gl.postings] == [(10_000, "MT55"), (1_800, "MT55")]
    gl = load_document(conn, cid, inventory.load_document(cid, imported).gl_document_id or 0)
    assert [(p.invoice, p.invoice_kind) for p in gl.postings] == [
        ("AZ1000/060326/0001234", CUSTOMS)
    ]
    rows = {(r.kind, r.invoice): r for r in invoice_report(conn, cid, "2026-03-01", "2026-03-31")}
    bought = rows[("", "MT55")]
    assert (bought.credit, bought.vat, bought.balance) == (11_800, 1_800, -11_800)
    assert rows[(CUSTOMS, "AZ1000/060326/0001234")].credit == 30_000


def test_receipt_form_shows_and_saves_the_basis(firm, qtbot):
    from PySide6.QtWidgets import QApplication

    from modern_gl.application.inventory import Inventory, ReceiptLine
    from modern_gl.desktop import theme
    from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
    from modern_gl.desktop.session import Session
    from modern_gl.domain.invoice import CUSTOMS

    conn, ledger, cid, acc, v = firm
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "шт", "Штука", precision=0)
    item = inventory.add_item(cid, "Бумага", unit, acc["41"])
    store = inventory.add_warehouse(cid, "Склад")
    draft = inventory.create_receipt_draft(
        cid,
        "2026-03-05",
        [ReceiptLine(item, store, "1", "10")],
        acc["60"],
        (v["Альфа"], v["Д-1"]),
        invoice="MT9",
    )
    theme.apply(QApplication.instance())
    s = Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _m: None)
    page = InventoryDocumentPage(s, doc_type="receipt")
    qtbot.addWidget(page)
    page.load(draft)
    assert page.invoice.text() == "MT9" and page.basis.currentData() == ""
    assert not page.invoice.isHidden()
    page.basis.setCurrentIndex(page.basis.findData(CUSTOMS))
    page.invoice.setText("AZ7")
    assert page.save(post=False)
    doc = inventory.load_document(cid, draft)
    assert (doc.invoice, doc.invoice_kind) == ("AZ7", CUSTOMS)


def test_a_payment_is_offered_the_e_qaime_of_drafts_and_of_the_portal(firm):
    """Paying Alfa (VÖEN 1234567890) on 06.03. Hand-calculated:
    MT1 posted 01.03 1 180.00, paid 1 000.00 on 02.03            -> 180.00
    MT2 only in a journal draft 03.03 500.00 to «Альфа-2» (the same VÖEN),
        paid 200.00 on 04.03                                       -> 300.00, a draft
    MT3 only in a purchase draft 05.03: 100.00 + ƏDV 18.00         -> 118.00, a draft
    MT4 only on the portal, 05.03, 236.00 with ƏDV                 -> 236.00, the portal
    Not offered: MT1 again from the portal (the books have it), MT5 annulled on the portal,
    MT6 a sale on the portal, MT7 dated after the payment, MT8 a draft of Beta."""
    from modern_gl.application.inventory import Inventory, ReceiptLine
    from modern_gl.domain.eqaime import PortalInvoice
    from modern_gl.reporting.invoices import DRAFT, PORTAL, open_invoices

    conn, ledger, cid, acc, v = firm
    kind = ledger.subconto_kind_id(cid, "counterparty")
    alfa2 = ledger.add_subconto_value(cid, kind, "Альфа-2")
    ledger.set_subconto_value_tax(cid, alfa2, "1234567890")
    rent, bank = (v["Аренда"],), (v["Kapital"],)
    alfa = (v["Альфа"], v["Д-1"])

    def bought(dt_sc, amount, number):
        return PostingInput(acc["26"], acc["60"], amount, rent, dt_sc, invoice=number)

    def paid(amount, number):
        return PostingInput(acc["60"], acc["51"], amount, alfa, bank, invoice=number)

    ledger.post_new(cid, "2026-03-01", [bought(alfa, "1180", "MT1")])
    ledger.post_new(cid, "2026-03-02", [paid("1000", "MT1")])
    ledger.create_draft(cid, "2026-03-03", [bought((alfa2,), "500", "MT2")])
    ledger.post_new(cid, "2026-03-04", [paid("200", "MT2")])
    ledger.create_draft(cid, "2026-03-05", [bought((v["Бета"],), "70", "MT8")])
    inventory = Inventory(conn, actor="test")
    unit = inventory.add_unit(cid, "шт", "Штука", precision=0)
    item = inventory.add_item(cid, "Бумага", unit, acc["41"])
    store = inventory.add_warehouse(cid, "Склад")
    inventory.create_receipt_draft(
        cid,
        "2026-03-05",
        [ReceiptLine(item, store, "10", "100", vat_amount="18")],
        acc["60"],
        alfa,
        invoice="MT3",
    )
    tin = "1234567890"
    ledger.remember_portal(
        cid,
        [
            PortalInvoice("MT1", False, "2026-03-01", "approved", tin, total=118_000),
            PortalInvoice("MT4", False, "2026-03-05", "approvedBySystem", tin, total=23_600),
            PortalInvoice("MT5", False, "2026-03-05", "canceled", tin, total=5_000),
            PortalInvoice("MT6", True, "2026-03-05", "approved", tin, total=7_000),
            PortalInvoice("MT7", False, "2026-03-10", "approved", tin, total=9_000),
        ],
    )
    found = open_invoices(conn, cid, v["Альфа"], payable=True, on_date="2026-03-06")
    assert [(i.invoice, i.amount, i.source) for i in found] == [
        ("MT1", 18_000, ""),
        ("MT2", 30_000, DRAFT),
        ("MT3", 11_800, DRAFT),
        ("MT4", 23_600, PORTAL),
    ]
    # what Alfa owes us: the 200.00 paid on MT2 while its purchase is a draft (as before),
    # and the sale MT6 on the portal
    owed = open_invoices(conn, cid, v["Альфа"], payable=False, on_date="2026-03-06")
    assert [(i.invoice, i.amount, i.source) for i in owed] == [
        ("MT2", 20_000, ""),
        ("MT6", 7_000, PORTAL),
    ]
