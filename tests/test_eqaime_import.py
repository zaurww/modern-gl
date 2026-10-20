"""Import of e-qaimə from the portal: the API client on a fake portal, parsing, the plan
(goods or service, what each line becomes) and the drafts. Numbers by hand in docstrings."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.eqaime_import import import_drafts, parse_invoice, plan_import
from modern_gl.application.inventory import QUANTITY_FACTOR, ReceiptLine, SaleLine
from modern_gl.infrastructure.etaxes import (
    APPROVED,
    EtaxesClient,
    PortalError,
    Response,
    TokenExpired,
)
from tests.test_sales import Shop, make_shop

SUPPLIER_TIN = "1700000001"
CUSTOMER_TIN = "1234567891"


def received(number: str = "MT2603000111", tin: str = SUPPLIER_TIN) -> tuple[dict, dict]:
    """A supplier's e-qaimə: 10 printers 120.00 (VAT base 120.00) and a repair 50.00
    (code 99…: a service, VAT base 50.00): VAT 21.60 + 9.00."""
    row = {
        "id": "a1",
        "sourceSystem": "avis",
        "serialNumber": number,
        "status": "approved",
        "kind": "defaultInvoice",
        "createdAt": "2026-03-05T15:32:56.394",
        "sender": {"tin": tin, "name": "Təchizatçı MMC"},
    }
    detail = {
        **row,
        "items": [
            {
                "productName": "Printer",
                "productGroup": {"code": "8443321000"},
                "unit": "ədəd",
                "quantity": 10,
                "pricePerUnit": 12,
                "cost": 120.0,
                "vat18": 120.0,
            },
            {
                "productName": "Printerin təmiri",
                "productGroup": {"code": "9995110000"},
                "unit": "xidmət",
                "quantity": 1,
                "cost": 50,
                "vat18": 50,
            },
        ],
    }
    return row, detail


@pytest.fixture
def shop(conn) -> Shop:
    return make_shop(conn, "classic")


def test_parse_reads_lines_kinds_and_vat():
    row, detail = received()
    invoice = parse_invoice(row, detail, outgoing=False)
    assert (invoice.number, invoice.doc_date, invoice.party_tin) == (
        "MT2603000111",
        "2026-03-05",
        SUPPLIER_TIN,
    )
    printer, repair = invoice.lines
    assert (printer.amount, printer.vat, printer.service) == (12_000, 2_160, False)
    assert printer.quantity == Decimal("10")
    assert (repair.amount, repair.vat, repair.service) == (5_000, 900, True)
    assert (invoice.amount, invoice.vat, invoice.doc_type) == (17_000, 3_060, "receipt")


def test_parse_without_lines_takes_the_totals():
    row = {
        "id": "b",
        "serialNumber": "mt 1",
        "createdAt": "2026-03-06",
        "costWithoutVat": 100,
        "vat": 18,
        "receiverTin": CUSTOMER_TIN,
        "receiverName": "Alfa",
    }
    invoice = parse_invoice(row, {}, outgoing=True)
    assert (invoice.number, invoice.party_name, invoice.doc_type) == ("MT1", "Alfa", "sale")
    assert [(line.amount, line.vat) for line in invoice.lines] == [(10_000, 1_800)]


def test_plan_and_import_a_purchase_as_a_draft(shop, conn):
    """A new supplier: added with its VÖEN. «Printer» is an item of that name; the repair
    (a service) has no account yet — the draft cannot post until the user chooses one."""
    plan = plan_import(conn, shop.company_id, [parse_invoice(*received(), outgoing=False)])[0]
    assert plan.counterparty_id is None and plan.importable
    assert [(p.item_id, p.found) for p in plan.lines] == [(shop.item, "name"), (None, "")]
    assert plan.unresolved == 1

    (draft,) = import_drafts(shop.inventory, shop.company_id, [plan])
    doc = shop.inventory.load_document(shop.company_id, draft)
    assert (doc.doc_type, doc.status, doc.invoice, doc.doc_date) == (
        "receipt",
        "draft",
        "MT2603000111",
        "2026-03-05",
    )
    printer, repair = doc.lines
    assert (printer.item_id, printer.warehouse_id, printer.quantity) == (
        shop.item,
        shop.main,
        10 * QUANTITY_FACTOR,
    )
    assert (printer.amount, printer.vat_amount) == (12_000, 2_160)
    assert (repair.item_id, repair.memo, repair.amount, repair.vat_amount) == (
        None,
        "Printerin təmiri",
        5_000,
        900,
    )
    supplier = conn.execute(
        "SELECT name, tax_id FROM subconto_values WHERE id = ?", (printer.offset_subconto[0],)
    ).fetchone()
    assert tuple(supplier) == ("Təchizatçı MMC", SUPPLIER_TIN)
    assert printer.offset_account_id == shop.acc["60"]
    with pytest.raises(Exception, match="строка 2: не указан счёт затрат"):
        shop.inventory.post_document(shop.company_id, draft)

    again = plan_import(conn, shop.company_id, [parse_invoice(*received(), outgoing=False)])[0]
    assert again.existing == doc.number and not again.importable  # no second copy


def test_plan_remembers_what_a_line_became_last_time(shop, conn):
    """Last time the supplier's «Printerin təmiri» went to 26 [Təmir]: the next e-qaimə of
    that supplier gets the same; «Printer» is found by name."""
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    repair = shop.ledger.add_subconto_value(shop.company_id, kind, "Təmir")
    shop.ledger.set_subconto_value_tax(shop.company_id, shop.supplier[0], SUPPLIER_TIN)
    shop.inventory.post_receipt(
        shop.company_id,
        "2026-02-01",
        [
            ReceiptLine(
                None,
                None,
                None,
                "40",
                "Printerin təmiri",
                expense_account_id=shop.acc["26"],
                expense_subconto=[repair],
            )
        ],
        shop.acc["60"],
        shop.supplier,
    )
    plan = plan_import(
        conn, shop.company_id, [parse_invoice(*received("MT2603000222"), outgoing=False)]
    )[0]
    assert plan.counterparty_id == shop.supplier[0]
    service = plan.lines[1]
    assert (service.account_id, service.subconto[0], service.found) == (
        shop.acc["26"],
        repair,
        "history",
    )
    assert plan.unresolved == 0


def test_import_a_sale_and_skip_a_return(shop, conn):
    """A sent e-qaimə: 3 printers 60.00 + VAT 10.80 to a known customer → a sale draft;
    a return e-qaimə is not imported."""
    shop.ledger.set_subconto_value_tax(shop.company_id, shop.customer, CUSTOMER_TIN)
    row = {
        "id": "s1",
        "serialNumber": "MT2603000333",
        "createdAt": "2026-03-07T10:00:00",
        "kind": "defaultInvoice",
        "receiver": {"tin": CUSTOMER_TIN, "name": "Alfa"},
    }
    detail = {
        **row,
        "items": [
            {
                "productName": "printer",
                "productGroup": {"code": "8443"},
                "quantity": "3",
                "cost": "60",
                "vat18": "60",
            }
        ],
    }
    sale = parse_invoice(row, detail, outgoing=True)
    returned = parse_invoice({**row, "id": "r"}, {**detail, "kind": "returnInvoice"}, outgoing=True)
    plans = plan_import(conn, shop.company_id, [sale, returned])
    assert plans[1].skip_reason and not plans[1].importable
    (draft,) = import_drafts(shop.inventory, shop.company_id, plans)
    doc = shop.inventory.load_document(shop.company_id, draft)
    (line,) = doc.lines
    assert doc.doc_type == "sale"
    assert (line.item_id, line.amount, line.vat_amount) == (shop.item, 6_000, 1_080)
    assert line.offset_subconto[0] == shop.customer
    assert line.offset_account_id == shop.acc["62"]
    # the customer's contract is left to the user; with it the draft posts
    shop.receipt("2026-03-01", "10", "120")
    shop.inventory.update_sale_draft(
        shop.company_id,
        draft,
        "2026-03-07",
        [SaleLine(shop.item, shop.main, "3", "60", "10.80", "printer", line_id=line.id)],
        shop.acc["62"],
        [shop.customer, shop.contract],
        vat_rate=1800,
        invoice="MT2603000333",
    )
    shop.inventory.post_document(shop.company_id, draft)


class FakePortal:
    """Answers like new.e-taxes.gov.az: pages of 50, one status per request."""

    def __init__(self, rows: dict[str, list[dict]], details: dict[str, dict]) -> None:
        self.rows, self.details, self.calls = rows, details, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        if headers["x-authorization"] != "Bearer good":
            return Response(401, b"")
        if method == "POST":
            request = json.loads(body)
            rows = self.rows.get(request["statuses"][0], [])
            page = rows[request["offset"] : request["offset"] + request["maxCount"]]
            more = request["offset"] + request["maxCount"] < len(rows)
            return Response(200, json.dumps({"invoices": page, "hasMore": more}).encode())
        invoice_id = url.rsplit("/", 1)[1].split("?")[0]
        if invoice_id not in self.details:
            return Response(500, b"INTERNAL_SERVICE_EXCEPTION")
        return Response(200, json.dumps({"invoice": self.details[invoice_id]}).encode())


def test_client_pages_statuses_and_reads_details():
    rows = [{"id": str(i), "serialNumber": f"MT{i}"} for i in range(60)]
    portal = FakePortal({"approved": rows, "approvedBySystem": [{"id": "x"}]}, {"7": {"id": "7"}})
    client = EtaxesClient("good", send=portal)
    got = list(client.invoices(False, date(2026, 3, 1), date(2026, 3, 31)))
    assert len(got) == 61  # two pages of «approved», one of «approvedBySystem»
    first = portal.calls[0]
    assert first[1].endswith("/find.inbox") and first[3]["creationDateFrom"] == "01-03-2026 00:00"
    assert first[3]["creationDateTo"] == "31-03-2026 23:59"
    assert len(portal.calls) == 1 + 1 + len(APPROVED) - 1
    assert client.detail("7", "avis") == {"id": "7"}
    with pytest.raises(PortalError, match="портал ответил 500"):
        client.detail("8", "avis")
    with pytest.raises(TokenExpired):
        list(EtaxesClient("old", send=portal).invoices(True, date(2026, 3, 1), date(2026, 3, 2)))


def fake_token(voen: str = "1402375141", name: str = "ДЕМО MMC", lifetime: int = 600) -> str:
    import base64
    import time

    payload = {"voen": voen, "organizationName": name, "exp": int(time.time()) + lifetime}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"head.{body}.sign"


def test_token_helpers():
    from modern_gl.desktop.portal_login import company_name, company_tin, token_alive

    token = fake_token()
    assert token_alive(token) and not token_alive(fake_token(lifetime=30))
    assert not token_alive("junk") and not token_alive(None)
    assert (company_tin(token), company_name(token)) == ("1402375141", "ДЕМО MMC")


def test_import_dialog_loads_shows_and_creates_drafts(shop, conn, qtbot, monkeypatch):
    """Signed in (a fake token), the dialog loads one received e-qaimə from a fake portal
    off the window's thread, shows it with its two lines, and makes one purchase draft."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import eqaime_import_page
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
    from modern_gl.desktop.session import Session

    row, detail = received()
    portal = FakePortal({"approved": [row]}, {"a1": detail})
    real_client = eqaime_import_page.EtaxesClient
    monkeypatch.setattr(
        eqaime_import_page, "EtaxesClient", lambda token: real_client("good", send=portal)
    )
    session = Session(
        conn,
        shop.ledger,
        shop.company_id,
        "Mağaza",
        Catalog(conn, shop.company_id),
        working_date=date(2026, 3, 20),
    )
    dialog = EqaimeImportDialog(session, sign_in=lambda parent: fake_token())
    qtbot.addWidget(dialog)
    dialog.sales.setChecked(False)
    dialog.load()
    qtbot.waitUntil(lambda: dialog.tree.topLevelItemCount() == 1, timeout=5000)
    assert "VÖEN 1402375141" in dialog.company.text()
    item = dialog.tree.topLevelItem(0)
    assert item is not None
    assert (item.text(1), item.text(2), item.childCount()) == ("MT2603000111", "Təchizatçı MMC", 2)
    assert "новый контрагент" in item.text(7) and "проверить строк: 1" in item.text(7)
    printer, repair = item.child(0), item.child(1)
    assert printer is not None and repair is not None
    assert printer.text(7).startswith("товар «Printer»") and printer.text(4) == "Товар"
    assert (repair.text(4), repair.text(7)) == ("Услуга", "выберите товар или счёт")
    assert dialog.import_button.text() == "Создать черновики: 1"

    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert not dialog.import_button.isEnabled()
    item.setCheckState(0, Qt.CheckState.Checked)
    dialog.create_drafts()
    assert len(dialog.created) == 1
    assert shop.inventory.load_document(shop.company_id, dialog.created[0]).status == "draft"
