"""Import of e-qaimə from the portal: the API client on a fake portal, parsing, the plan
(goods or service, what each line becomes) and the drafts. Numbers by hand in docstrings."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.eqaime import EInvoice, import_drafts, parse_invoice, plan_import
from modern_gl.application.inventory import QUANTITY_FACTOR, ReceiptLine, SaleLine
from modern_gl.infrastructure.etaxes import (
    APPROVED,
    EtaxesClient,
    PortalError,
    TokenExpiredError,
)
from tests.helpers.eqaime import SUPPLIER_TIN, FakePortal, fake_token, received
from tests.helpers.qt import table_item
from tests.helpers.sales import Shop, make_shop

CUSTOMER_TIN = "1234567891"


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
    # a return e-qaimə the company sent is its goods going back (the buyer writes it, the
    # seller approves): a return to the supplier, on the suppliers' account
    assert plans[1].importable and plans[1].return_type == "purchase_return"
    draft, back = import_drafts(shop.inventory, shop.company_id, plans)
    returned_doc = shop.inventory.load_document(shop.company_id, back)
    assert returned_doc.doc_type == "purchase_return" and returned_doc.invoice == "MT2603000333"
    assert returned_doc.lines[0].offset_account_id == shop.acc["60"]
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
    with pytest.raises(TokenExpiredError):
        list(EtaxesClient("old", send=portal).invoices(True, date(2026, 3, 1), date(2026, 3, 2)))


def test_token_helpers():
    from modern_gl.desktop.portal_login import company_name, company_tin, token_alive

    token = fake_token()
    assert token_alive(token) and not token_alive(fake_token(lifetime=30))
    assert not token_alive("junk") and not token_alive(None)
    assert (company_tin(token), company_name(token)) == ("1402375141", "ДЕМО MMC")


def test_a_purchase_imported_with_an_earlier_expense_month(shop, conn):
    """The repair of February on the e-qaimə of 05.03 (D65): 50.00 + ƏDV 9.00 on 26.
    Posted: 28.02 Dt 26 / Kt 76H 50.00; 05.03 Dt 41 / Kt 60 120.00, Dt 76H / Kt 60 50.00,
    Dt 19 / Kt 60 30.60 = 21.60 + 9.00. A purchase of goods alone has no expense month."""
    plan = plan_import(conn, shop.company_id, [parse_invoice(*received(), outgoing=False)])[0]
    assert plan.has_expenses
    kind = shop.ledger.subconto_kind_id(shop.company_id, "cost_item")
    repair = shop.ledger.add_subconto_value(shop.company_id, kind, "Təmir")
    plan.lines[1].account_id, plan.lines[1].subconto = shop.acc["26"], (repair,)
    plan.expense_date = "2026-02-28"
    (draft,) = import_drafts(shop.inventory, shop.company_id, [plan])
    shop.inventory.post_document(shop.company_id, draft)
    assert [p[:3] for p in shop.postings(draft)] == [
        ("41", "60", 12_000),
        ("76H", "60", 5_000),
        ("19", "60", 3_060),
    ]
    doc = shop.inventory.load_document(shop.company_id, draft)
    assert [line.expense_date for line in doc.lines] == [None, "2026-02-28"]  # goods, repair
    (accrual,) = [a.gl_document_id for a in doc.accruals]
    row = conn.execute(
        "SELECT d.doc_date, p.debit_account_id, p.credit_account_id, p.amount "
        "FROM postings p JOIN documents d ON d.id = p.document_id WHERE d.id = ?",
        (accrual,),
    ).fetchone()
    assert tuple(row) == ("2026-02-28", shop.acc["26"], shop.acc["76H"], 5_000)

    goods = plan_import(conn, shop.company_id, [parse_invoice(*received("MT2"), outgoing=False)])
    goods[0].lines.pop()  # the printers alone
    assert not goods[0].has_expenses


def test_import_dialog_loads_shows_and_creates_drafts(shop, conn, qtbot, monkeypatch):
    """Signed in (a fake token), the dialog loads one received e-qaimə from a fake portal
    off the window's thread, shows it with its two lines, and makes one purchase draft."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop import eqaime_import_page
    from modern_gl.desktop.eqaime_import_page import EXPENSE_MONTH, EqaimeImportDialog
    from modern_gl.desktop.pick import PickBox
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
    shop.ledger.set_company_tax_id(shop.company_id, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeImportDialog(session, sign_in=lambda parent: fake_token())
    qtbot.addWidget(dialog)
    dialog.sales.setChecked(False)
    dialog.load()
    qtbot.waitUntil(lambda: dialog.tree.topLevelItemCount() == 1, timeout=5000)
    assert "VÖEN 1402375141" in dialog.company.text()
    item = dialog.tree.topLevelItem(0)
    assert item is not None
    assert (item.text(1), item.text(2), item.childCount()) == ("MT2603000111", "Təchizatçı MMC", 2)
    assert "новый контрагент" in item.text(8) and "проверить строк: 1" in item.text(8)
    printer, repair = item.child(0), item.child(1)
    assert printer is not None and repair is not None
    assert printer.text(8).startswith("товар «Printer»") and printer.text(4) == "Товар"
    assert (repair.text(4), repair.text(8)) == ("Услуга", "выберите товар или счёт")
    assert dialog.import_button.text() == "Создать черновики: 1"

    # the repair may be February's: the e-qaimə's month or one of the twelve before (D65)
    box = dialog.tree.itemWidget(item, EXPENSE_MONTH)
    assert isinstance(box, PickBox)
    months = [box.itemData(i) for i in range(box.count())]
    assert (months[:3], len(months)) == ([None, "2026-02-28", "2026-01-31"], 13)
    box.setCurrentIndex(1)
    box.activated.emit(1)

    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert not dialog.import_button.isEnabled()
    item.setCheckState(0, Qt.CheckState.Checked)
    dialog.create_drafts()
    assert len(dialog.created) == 1
    draft = shop.inventory.load_document(shop.company_id, dialog.created[0])
    assert draft.status == "draft"
    assert [line.expense_date for line in draft.lines if line.item_id is None] == ["2026-02-28"]


@pytest.mark.parametrize(
    ("portal", "short"),
    [
        ('"ALFA TREYD" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ', "ALFA TREYD MMC"),
        ("«Azərsun Holdinq» məhdud məsuliyyətli cəmiyyəti", "Azərsun Holdinq MMC"),
        ("AÇIQ SƏHMDAR CƏMİYYƏTİ  “KAPİTAL BANK”", "KAPİTAL BANK ASC"),
        ("Məmmədov Rauf Fərdi sahibkar", "Məmmədov Rauf FS"),
        ("Kompyuter Dünyası", "Kompyuter Dünyası"),
    ],
)
def test_short_name_suggests_a_shorter_counterparty_name(portal, short):
    from modern_gl.application.eqaime import short_name

    assert short_name(portal) == short


def test_one_new_counterparty_per_voen_named_by_the_user(shop, conn):
    """Two e-qaimə of one new supplier: it is listed once and added once, under the name
    the user typed; the documents point at it."""
    from modern_gl.application.eqaime import new_counterparties

    long_name = '"KOMPYUTER DÜNYASI" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ'
    invoices = []
    for number in ("MT1", "MT2"):
        row, detail = received(number)
        detail["sender"] = {"tin": SUPPLIER_TIN, "name": long_name}
        invoices.append(parse_invoice(row, detail, outgoing=False))
    plans = plan_import(conn, shop.company_id, invoices)
    (party,) = new_counterparties(plans)
    assert (party.tax_id, party.portal_name, party.name, party.invoices) == (
        SUPPLIER_TIN,
        long_name,
        "KOMPYUTER DÜNYASI MMC",
        2,
    )
    drafts = import_drafts(shop.inventory, shop.company_id, plans, {party.key: "Kompyuter Dünyası"})
    suppliers = conn.execute(
        "SELECT id, name FROM subconto_values WHERE company_id = ? AND tax_id = ?",
        (shop.company_id, SUPPLIER_TIN),
    ).fetchall()
    assert [row["name"] for row in suppliers] == ["Kompyuter Dünyası"]
    for draft in drafts:
        doc = shop.inventory.load_document(shop.company_id, draft)
        assert doc.lines[0].offset_subconto[0] == suppliers[0]["id"]


def test_counterparties_can_be_added_before_any_document(shop, conn):
    """«Add counterparties» alone: no documents; the next plan finds them by VÖEN."""
    from modern_gl.application.eqaime import add_counterparties, new_counterparties

    plans = plan_import(conn, shop.company_id, [parse_invoice(*received(), outgoing=False)])
    parties = new_counterparties(plans)
    parties[0].name = "Təchizatçı"
    ids = add_counterparties(shop.ledger, shop.company_id, parties, plans)
    assert plans[0].counterparty_id == ids[SUPPLIER_TIN]
    assert conn.execute("SELECT COUNT(*) FROM inventory_documents").fetchone()[0] == 0
    again = plan_import(conn, shop.company_id, [parse_invoice(*received(), outgoing=False)])
    assert again[0].counterparty_id == ids[SUPPLIER_TIN] and not new_counterparties(again)


def test_import_dialog_adds_counterparties_with_edited_names(shop, conn, qtbot):
    """The new supplier is listed once with a shortened name; the user corrects it and adds
    the counterparties alone; the e-qaimə is then no longer «a new counterparty»."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
    from modern_gl.desktop.session import Session

    long_name = '"KOMPYUTER DÜNYASI" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ'
    invoices = []
    for number in ("MT1", "MT2"):
        row, detail = received(number)
        detail["sender"] = {"tin": SUPPLIER_TIN, "name": long_name}
        invoices.append(parse_invoice(row, detail, outgoing=False))
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    shop.ledger.set_company_tax_id(shop.company_id, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeImportDialog(session)
    qtbot.addWidget(dialog)
    assert dialog.parties.isHidden()  # nothing loaded yet
    dialog.show_invoices(invoices)
    assert not dialog.parties.isHidden() and dialog.parties.rowCount() == 1
    texts = [table_item(dialog.parties, 0, c).text() for c in range(4)]
    assert texts == [SUPPLIER_TIN, long_name, "KOMPYUTER DÜNYASI MMC", "2"]
    assert dialog.parties_title.text() == "Новые контрагенты: 1"

    table_item(dialog.parties, 0, 2).setText("  Kompyuter   Dünyası ")
    dialog.add_parties()
    supplier = conn.execute(
        "SELECT name FROM subconto_values WHERE tax_id = ?", (SUPPLIER_TIN,)
    ).fetchone()
    assert supplier["name"] == "Kompyuter Dünyası"
    assert dialog.parties.isHidden()
    first = dialog.tree.topLevelItem(0)
    assert first is not None and "новый контрагент" not in first.text(8)
    assert conn.execute("SELECT COUNT(*) FROM inventory_documents").fetchone()[0] == 0


def test_counterparty_without_voen_is_found_by_its_exact_name(shop, conn):
    """«Alfa» has no VÖEN in the company: an e-qaimə of «ALFA» without VÖEN finds it;
    one with a VÖEN never matches by name."""
    row = {
        "id": "n",
        "serialNumber": "MT9",
        "createdAt": "2026-03-07",
        "costWithoutVat": 10,
        "receiverName": " ALFA ",
        "receiverTin": "",
    }
    (plan,) = plan_import(conn, shop.company_id, [parse_invoice(row, {}, outgoing=True)])
    assert plan.counterparty_id == shop.customer
    row["receiverTin"] = CUSTOMER_TIN
    (plan,) = plan_import(conn, shop.company_id, [parse_invoice(row, {}, outgoing=True)])
    assert plan.counterparty_id is None


def _named(number: str, day: str, name: str) -> EInvoice:
    row, detail = received(number)
    detail["sender"] = {"tin": SUPPLIER_TIN, "name": name}
    detail["createdAt"] = f"{day}T10:00:00"
    return parse_invoice(row, detail, outgoing=False)


def test_a_counterparty_renamed_on_the_portal_is_asked_about(shop, conn):
    """Imported once as «"ALFA" MMC» (named «Alfa» here); in March its e-qaimə say «"BETA
    TREYD" MMC» with the same VÖEN: listed as renamed, with the latest name; renaming
    changes the name here and remembers the new official one; quotes and case alone are
    no rename."""
    from modern_gl.application.eqaime import (
        apply_renames,
        new_counterparties,
        renamed_counterparties,
    )

    first = plan_import(conn, shop.company_id, [_named("MT1", "2026-02-01", '"ALFA" MMC')])
    (party,) = new_counterparties(first)
    import_drafts(shop.inventory, shop.company_id, first, {party.key: "Alfa"})
    value = conn.execute(
        "SELECT id, name, legal_name FROM subconto_values WHERE tax_id = ?", (SUPPLIER_TIN,)
    ).fetchone()
    assert (value["name"], value["legal_name"]) == ("Alfa", '"ALFA" MMC')

    same = plan_import(conn, shop.company_id, [_named("MT2", "2026-03-01", "«alfa»  mmc")])
    assert renamed_counterparties(conn, shop.company_id, same) == []

    march = plan_import(
        conn,
        shop.company_id,
        [
            _named("MT3", "2026-03-02", '"ALFA" MMC'),
            _named("MT4", "2026-03-20", '"BETA TREYD" MMC'),
        ],
    )
    (renamed,) = renamed_counterparties(conn, shop.company_id, march)
    assert (renamed.value_id, renamed.old_legal_name, renamed.new_legal_name) == (
        value["id"],
        '"ALFA" MMC',
        '"BETA TREYD" MMC',
    )
    assert (renamed.current_name, renamed.name, renamed.rename) == ("Alfa", "BETA TREYD MMC", True)
    renamed.name = "Beta Treyd"
    apply_renames(shop.ledger, shop.company_id, [renamed])
    after = conn.execute(
        "SELECT name, legal_name FROM subconto_values WHERE id = ?", (value["id"],)
    ).fetchone()
    assert tuple(after) == ("Beta Treyd", '"BETA TREYD" MMC')
    assert renamed_counterparties(conn, shop.company_id, march[1:]) == []


def test_a_kept_name_is_not_asked_about_again(shop, conn):
    """The user keeps its name here: only the official name is remembered."""
    from modern_gl.application.eqaime import apply_renames, renamed_counterparties

    shop.ledger.set_subconto_value_tax(shop.company_id, shop.supplier[0], SUPPLIER_TIN)
    shop.ledger.set_subconto_value_legal_name(shop.company_id, shop.supplier[0], "Köhnə MMC")
    plans = plan_import(conn, shop.company_id, [_named("MT5", "2026-03-01", "Yeni MMC")])
    (renamed,) = renamed_counterparties(conn, shop.company_id, plans)
    renamed.rename = False
    apply_renames(shop.ledger, shop.company_id, [renamed])
    row = conn.execute(
        "SELECT name, legal_name FROM subconto_values WHERE id = ?", (shop.supplier[0],)
    ).fetchone()
    assert tuple(row) == ("Təchizatçı", "Yeni MMC")
    assert renamed_counterparties(conn, shop.company_id, plans) == []


def test_a_known_counterparty_gets_its_official_name_quietly(shop, conn):
    """A counterparty made by hand (no official name) is not «renamed»: importing its
    e-qaimə remembers the portal's name."""
    from modern_gl.application.eqaime import renamed_counterparties

    shop.ledger.set_subconto_value_tax(shop.company_id, shop.supplier[0], SUPPLIER_TIN)
    plans = plan_import(conn, shop.company_id, [_named("MT6", "2026-03-01", "Rəsmi Ad MMC")])
    assert renamed_counterparties(conn, shop.company_id, plans) == []
    import_drafts(shop.inventory, shop.company_id, plans)
    row = conn.execute(
        "SELECT name, legal_name FROM subconto_values WHERE id = ?", (shop.supplier[0],)
    ).fetchone()
    assert tuple(row) == ("Təchizatçı", "Rəsmi Ad MMC")


def test_import_dialog_renames_a_counterparty(shop, conn, qtbot):
    """The renamed supplier is listed with old and new portal names; unticked it keeps its
    name here, the new official name is remembered and the block goes away."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
    from modern_gl.desktop.session import Session

    shop.ledger.set_subconto_value_tax(shop.company_id, shop.supplier[0], SUPPLIER_TIN)
    shop.ledger.set_subconto_value_legal_name(shop.company_id, shop.supplier[0], '"ALFA" MMC')
    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    shop.ledger.set_company_tax_id(shop.company_id, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeImportDialog(session)
    qtbot.addWidget(dialog)
    assert dialog.renames.isHidden()
    dialog.show_invoices([_named("MT7", "2026-03-01", '"BETA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ')])
    assert not dialog.renames.isHidden() and dialog.renames.rowCount() == 1
    texts = [table_item(dialog.renames, 0, c).text() for c in range(5)]
    assert texts == [
        SUPPLIER_TIN,
        '"ALFA" MMC',
        '"BETA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ',
        "Təchizatçı",
        "BETA MMC",
    ]
    assert dialog.renames_title.text() == "Название изменилось: 1"
    table_item(dialog.renames, 0, 0).setCheckState(Qt.CheckState.Unchecked)
    dialog.apply_renames()
    row = conn.execute(
        "SELECT name, legal_name FROM subconto_values WHERE id = ?", (shop.supplier[0],)
    ).fetchone()
    assert tuple(row) == ("Təchizatçı", '"BETA" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ')
    assert dialog.renames.isHidden()


@pytest.mark.parametrize(
    ("direction", "purchases", "sales"), [("receipt", True, False), ("sale", False, True)]
)
def test_import_dialog_from_a_section_loads_one_direction(
    shop, conn, qtbot, direction, purchases, sales
):
    """From «Alış» only received e-qaimə, from «Satış» only sent ones (D46)."""
    from modern_gl.application.catalog import Catalog
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
    from modern_gl.desktop.session import Session

    session = Session(conn, shop.ledger, shop.company_id, "Mağaza", Catalog(conn, shop.company_id))
    shop.ledger.set_company_tax_id(shop.company_id, "1402375141")  # the portal's firm (D113)
    dialog = EqaimeImportDialog(session, direction=direction)
    qtbot.addWidget(dialog)
    assert (dialog.purchases.isChecked(), dialog.sales.isChecked()) == (purchases, sales)
    assert dialog.purchases.isHidden() and dialog.sales.isHidden()
