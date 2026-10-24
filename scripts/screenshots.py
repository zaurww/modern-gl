"""Render the main screens of the demo company to PNG (for design review).

uv run python scripts/screenshots.py [out_dir] [az|ru] [theme]
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":  # the offscreen platform doesn't see system fonts by itself
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QLineEdit

from modern_gl import i18n
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import qt_texts, theme
from modern_gl.desktop.app import add_demo_company
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.opening_balances_page import OpeningBalancesPage
from modern_gl.desktop.reports_page import OsvPage, StatementsPage, SubcontoPage


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    i18n.set_language(sys.argv[2] if len(sys.argv) > 2 else "az")
    app = QApplication(sys.argv)
    theme.set_theme(sys.argv[3] if len(sys.argv) > 3 else theme.DEFAULT_THEME)
    theme.apply(app)
    qt_texts.install(app)
    workspace = Workspace(Path(tempfile.mkdtemp()))
    add_demo_company(workspace)
    win = MainWindow(workspace)
    win.start()
    session, ledger = win.session, win.ledger
    assert session is not None and ledger is not None  # the demo company is open
    session.working_date = date(2026, 2, 28)
    win.resize(1400, 860)
    win.show()

    def shot(name: str) -> None:
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)  # let the page fade-in finish
        loop.exec()
        image = win.grab()
        popup = next(
            (
                w
                for w in QApplication.topLevelWidgets()
                if w.objectName() in ("completer", "palette", "periodWindow") and w.isVisible()
            ),
            None,
        )
        if popup is not None:  # popups are separate windows: paint them in place
            painter = QPainter(image)
            painter.drawPixmap(
                win.mapFromGlobal(popup.mapToGlobal(popup.rect().topLeft())), popup.grab()
            )
            painter.end()
        image.save(str(out / f"{name}.png"))
        print(out / f"{name}.png")

    win.show_place(("home",))  # read again on the working date set above
    shot("0_home")  # «Bu gün», the first page (D86)
    win.show_place(("journal",))
    shot("1_journal")
    journal = cast(JournalPage, win.pages[("journal",)])
    journal.quick.edit.setText("71 " + i18n.tr("Мамедов Р.").split()[0][:5] + " / 50 120 Avans")
    journal.focus_quick_entry()
    shot("1b_quick_entry")
    journal.quick.edit.setText("26 ")  # the list offers 26's cost items
    journal.quick.edit.setCursorPosition(3)
    journal.quick.suggest()
    shot("1d_quick_suggest")
    journal.quick.completer.popup().hide()
    journal.quick.edit.clear()
    palette = win.command_palette()  # Ctrl+K: find and do anything (D86)
    assert palette is not None
    palette.search.setText("60")
    shot("14_command_palette")
    palette.close()
    win.show_import()
    importer = win.pages[("import",)]
    alfa = i18n.tr("Альфа Трейд").split()[0]
    contract = i18n.tr("Договор поставки №1")
    bank = i18n.tr("Основной расчётный счёт")
    importer.paste(
        "\n".join(
            [
                "Tarix\tSənəd\tDebet\tSubkonto\tKredit\tSubkonto\tSubkonto\tMəbləğ\tMəzmun",
                f"02.03.2026\t1\t26\t{i18n.tr('Аренда офиса')}\t60\t{alfa}\t{contract}\t400\tMart",
                f"03.03.2026\t2\t60\t{alfa}\t51\t{bank}\t\t400\tÖdəniş",
                "04.03.2026\t3\t50\t\t51\t\t\t1 000,00\tKassaya",
                "05.03.2026\t4\t71\t\t50\t\t\t150\tAvans",
            ]
        )
    )
    shot("1c_import")
    win.close_page(("import",), ask=False)
    docs = cast(JournalPage, win.pages[("journal",)]).model.docs
    win.open_document(next(d.id for d in docs if len(d.memo) and d.lines == 2))
    shot("2_document_posted")
    win.open_document(next(d.id for d in docs if d.status == "draft"))
    shot("3_document_draft")
    win.new_document()
    page = cast(DocumentPage, win.stack.currentWidget())
    cat = session.catalog
    page.memo.setText(i18n.tr("Аренда за март"))
    page.model.setData(page.model.index(0, 0), cat.by_code["26"].id)
    page.model.setData(page.model.index(0, 4), cat.by_code["60"].id)
    shot("4_document_new")
    idx = page.model.index(0, 5)
    page.table.setCurrentIndex(idx)
    page.table.edit(idx)
    shot("4b_subconto_list")
    page.table.setFocus()
    idx = page.model.index(page.model.insert_row(), 0)  # a group typed in full: its accounts
    page.table.setCurrentIndex(idx)
    page.table.edit(idx)
    editor = next(w for w in page.table.findChildren(QLineEdit) if w.isVisible())
    editor.insert("68")
    editor.textEdited.emit(editor.text())
    editor.returnPressed.emit()
    shot("4c_group_account")
    page.table.setFocus()
    win.show_place(("osv",))
    shot("5_osv")
    osv = cast(OsvPage, win.pages[("osv",)])
    for option, name in (
        (osv.top_only, "5b_osv_top_only"),
        (osv.sections, "5c_osv_sections"),
        (osv.expand, "5d_osv_expanded"),
    ):
        option.setChecked(True)
        shot(name)
        option.setChecked(False)
    win.show_place(("statements",))  # «Баланс и прибыль» (D99)
    shot("20_balance_sheet")
    statements = cast(StatementsPage, win.pages[("statements",)])
    statements.profit_button.click()
    shot("20b_profit_and_loss")
    statements.detail_buttons["items"].click()  # D102: the accounts and their cost items
    shot("20d_profit_by_items")
    statements.detail_buttons["accounts"].click()
    statements.cash_button.click()
    shot("20c_cash_flow")  # D100
    statements.profit_button.click()  # D107: months side by side, a comparison
    statements.period.set_period(date(2026, 1, 1), date(2026, 2, 28))
    statements.columns.choose("months")
    shot("20e_profit_by_months")
    statements.balance_button.click()
    statements.columns.choose("year_ago")
    shot("20f_balance_year_ago")
    statements.columns.choose("one")
    statements.period.show_presets()  # D105: the period with the mouse
    shot("20g_period_window")
    statements.period.window_shown.close()
    win.open_books()  # «Сравнение книг» (D98): the demo's IFRS write-down of stock
    shot("19_books_compare")
    win.close_current()
    win.show_place(("reports",))  # «Все отчёты» (D114): every report by group
    shot("21_reports")
    win.show_place(("osv",))
    win.show_place(("opening",))
    opening = cast(OpeningBalancesPage, win.pages[("opening",)])
    QApplication.clipboard().setText("Счёт\tДебет\tКредит\n50\t1750\t\n51\t5200\t\n80\t\t5000\n")
    opening.paste()  # the totals differ: the page shows the difference and its button
    shot("5e_opening_balances")
    win.open_report("subconto", session.catalog.by_code["60"].id, osv.params)
    shot("6_subconto")
    subconto = cast(SubcontoPage, win.stack.currentWidget())
    subconto.drill(subconto.model.rows[2])  # the card of one counterparty, with its lines
    shot("6b_subconto_card")
    win.open_report("card", session.catalog.by_code["51"].id, osv.params)
    shot("7_card")
    win.show_place(("chart",))
    shot("8_chart")
    win.resize(1100, 860)  # a laptop: the subconto column gives way, the type stays
    shot("8b_chart_narrow")
    win.resize(1400, 860)
    win.show_place(("directories",))
    directories = cast(DirectoriesPage, win.stack.currentWidget())
    banks = session.catalog.by_code["51"].sc_kinds[0]
    assert banks is not None  # 51 has the "bank accounts" directory
    for name in ("Kapital Bank", "ABB"):
        ledger.add_subconto_value(session.company_id, banks, name)
    session.catalog.reload()
    directories.refresh(select_kind=banks)
    shot("8b_directories")
    directories.refresh(select_kind=session.catalog.by_code["60"].sc_kinds[1])
    shot("8b2_contracts")
    from modern_gl.desktop.directories_page import ValueDialog

    contracts = session.catalog.by_code["60"].sc_kinds[1]
    alfa_id = next(v.id for v in session.catalog.values(session.catalog.owner_kinds[contracts]))
    value_dialog = ValueDialog(
        session, contracts, i18n.tr("Новый элемент"), "Faktura 15", alfa_id, win
    )
    value_dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    value_dialog.grab().save(str(out / "8b3_contract_dialog.png"))
    value_dialog.close()
    bank_dialog = ValueDialog(
        session, banks, i18n.tr("Новый элемент"), "Kapital Bank USD", None, win
    )
    bank_dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    bank_dialog.grab().save(str(out / "8b4_bank_dialog.png"))
    bank_dialog.close()
    from modern_gl.desktop.account_dialog import AccountDialog

    salary = session.catalog.by_code.get("70")
    if salary is not None:  # its employee may stay empty: paid in one sum (D78)
        account_dialog = AccountDialog(session, salary, parent=win)
        account_dialog.show()
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        account_dialog.grab().save(str(out / "8b9_account_dialog.png"))
        account_dialog.close()
    partners = session.catalog.owner_kinds[contracts]
    for i, v in enumerate(session.catalog.values(partners)):  # VÖEN of the demo partners
        ledger.set_subconto_value_tax(session.company_id, v.id, f"{1400057421 + i * 1111}")
    acme = ledger.add_subconto_value(session.company_id, partners, "Acme Trading GmbH")
    ledger.set_subconto_value_tax(
        session.company_id, acme, "DE 811 234 567", nonresident=True, country="Almaniya"
    )
    cid = session.company_id
    related = ledger.add_tag(cid, i18n.tr("Связанная сторона"))
    landlord = ledger.add_tag(cid, i18n.tr("Арендодатель"))
    ledger.add_tag(cid, i18n.tr("Холдинг"))
    tagged = session.catalog.values(partners)[1].id  # Бета: the dialog below shows it
    ledger.set_subconto_value_tags(cid, tagged, [related, landlord])
    ledger.set_subconto_value_tags(cid, acme, [related])
    session.catalog.reload()
    directories.refresh(select_kind=partners)
    shot("8b5_counterparties")
    for name, value in (
        ("8b6_counterparty_dialog", session.catalog.value(tagged)),
        ("8b7_nonresident_dialog", session.catalog.value(acme)),
    ):
        dialog = ValueDialog(
            session, partners, i18n.tr("Изменить"), value.name, None, win, None, value
        )
        dialog.show()
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        dialog.grab().save(str(out / f"{name}.png"))
        dialog.close()
    win.open_report("subconto", session.catalog.by_code["60"].id, osv.params)
    by_tag = cast(SubcontoPage, win.stack.currentWidget())
    by_tag.tag.setCurrentIndex(by_tag.tag.findData(related))
    by_tag.refresh()
    shot("6b_subconto_tag")
    win.show_place(("inventory",))
    inventory = cast(InventoryPage, win.stack.currentWidget())
    inventory.refresh()
    shot("8c_inventory")
    inventory.table.selectRow(1)  # an item: where its goods came from and went to
    shot("8c_inventory_movements")
    inventory.documents_button.click()
    shot("8c_inventory_documents")
    inventory.movements_button.click()
    win.new_inventory_document("incoming")  # D91: goods in without a purchase
    shot("8c1_incoming")
    win.close_current()
    inventory_document = min(  # the first one, with VAT
        (row for row in inventory.documents_model.rows if row.doc_type == "receipt"),
        key=lambda row: row.number,
    )
    win.open_inventory_document(inventory_document.id)
    assert isinstance(win.stack.currentWidget(), InventoryDocumentPage)
    shot("8c2_inventory_document")
    from modern_gl.reporting.trade import SALE, trade_documents

    sale = trade_documents(session.conn, session.company_id, SALE)[0]  # a service: not in stock
    win.open_inventory_document(sale.id)
    assert isinstance(win.stack.currentWidget(), InventoryDocumentPage)
    shot("8c8_sale")
    from modern_gl.desktop.inventory_page import InventorySettingsDialog

    settings_dialog = InventorySettingsDialog(session, win)
    settings_dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    settings_dialog.grab().save(str(out / "8c3_inventory_settings.png"))
    settings_dialog.close()
    from modern_gl.application.inventory import Inventory, LandedCostCharge, LandedCostTarget
    from modern_gl.application.ledger import PostingInput
    from modern_gl.desktop.landed_cost_page import cost_source_picker
    from modern_gl.reporting.inventory import receipt_line_choices

    cid, catalog = session.company_id, session.catalog
    partner = catalog.values(catalog.by_code["60"].sc_kinds[0])[1]
    contract = catalog.values(catalog.by_code["60"].sc_kinds[1], partner.id)[0]
    cost_item = catalog.values(catalog.by_code["44"].sc_kinds[0])[0]
    broker = ledger.post_new(
        cid,
        "2026-02-04",
        [
            PostingInput(
                catalog.by_code["44"].id,
                catalog.by_code["60"].id,
                "40",
                (cost_item.id,),
                (partner.id, contract.id),
                i18n.tr("Брокерские услуги"),
            )
        ],
    )
    stock = Inventory(session.conn, actor="screenshots")
    freight = stock.add_landed_cost_type(cid, i18n.tr("Доставка"))
    batch = stock.create_landed_cost_draft(
        cid,
        "2026-02-05",
        [
            LandedCostTarget(r.id)
            for r in sorted(receipt_line_choices(session.conn, cid), key=lambda r: r.id)
        ],
        [
            LandedCostCharge(
                "85", catalog.by_code["60"].id, (partner.id, contract.id), "15.30", freight
            ),
            LandedCostCharge("30", source_document_id=broker, source_line_no=1),
            LandedCostCharge(
                None,
                catalog.by_code["60"].id,
                (partner.id, contract.id),
                memo=i18n.tr("Фрахт"),
                currency_id=ledger.currency_id(cid, "USD"),
                currency_rate="1.7",
                currency_amount="25",
            ),
        ],
        "value",
        i18n.tr("Партия"),
    )
    stock.post_document(cid, batch)
    win.open_inventory_document(batch)
    shot("8c4_landed_cost")
    from modern_gl.desktop.landed_cost_page import BatchCostDialog

    report = BatchCostDialog(session, batch, i18n.tr("Партия"), win)
    report.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    report.grab().save(str(out / "8c6_batch_cost.png"))
    report.close()
    win.open_landed_report()
    shot("8c7_landed_report")
    win.new_inventory_document("receipt")
    receipt_page = cast(InventoryDocumentPage, win.stack.currentWidget())
    receipt_page.currency.setCurrentIndex(
        receipt_page.currency.findData(ledger.currency_id(cid, "USD"))
    )
    receipt_page.rate.setText("1.7")
    receipt_page._rate_edited()
    receipt_page.model.rows[0].item_id = next(iter(receipt_page.model.items))
    receipt_page.model.rows[0].quantity = 100 * 1_000_000
    receipt_page.model.setData(
        receipt_page.model.index(0, receipt_page.model.columns.index("currency_amount")), 50_000
    )
    shot("8c7_receipt_usd")
    from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine

    def kind_value(kind: str, name: str) -> int:
        return ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name)

    supplier = stock.load_document(cid, inventory_document.id).lines[0]  # the demo's own
    assert supplier.offset_account_id is not None
    purchase = stock.post_receipt(  # a purchase of a service and a fixed asset
        cid,
        "2026-02-26",
        [
            ReceiptLine(
                None,
                None,
                None,
                "50",
                i18n.tr("Ремонт принтера"),
                vat_amount="9",
                expense_account_id=ledger.account_id(cid, "26"),
                expense_subconto=[kind_value("cost_item", i18n.tr("Ремонт"))],
            ),
            ReceiptLine(
                None,
                None,
                "1",
                "1000",
                i18n.tr("Ноутбук"),
                vat_amount="180",
                expense_account_id=ledger.account_id(cid, "08"),
                expense_subconto=[kind_value("fixed_asset", i18n.tr("Ноутбук Dell"))],
            ),
        ],
        supplier.offset_account_id,
        supplier.offset_subconto,
        i18n.tr("Ремонт и ноутбук"),
        vat_rate=STANDARD_VAT_RATE,
        invoice="MT2602007788",
        expense_date="2026-01-31",  # the repair was January's (D65)
    )
    session.catalog.reload()  # the new cost item and fixed asset
    win.open_inventory_document(purchase)
    shot("8c9_purchase_services")
    for day in ("2026-02-27", "2026-02-28"):  # drafts from the portal: posted at once (D73)
        stock.create_receipt_draft(
            cid,
            day,
            [ReceiptLine(None, None, None, "40", i18n.tr("Ремонт принтера"), vat_amount="7.20")],
            supplier.offset_account_id,
            supplier.offset_subconto,
            vat_rate=STANDARD_VAT_RATE,
        )
    waiting = stock.create_receipt_draft(  # goods came before their e-qaimə (D119)
        cid,
        "2026-02-28",
        [
            ReceiptLine(
                None,
                None,
                None,
                "250",
                i18n.tr("Картриджи"),
                expense_account_id=ledger.account_id(cid, "26"),
                expense_subconto=[kind_value("cost_item", i18n.tr("Картриджи"))],
            )
        ],
        supplier.offset_account_id,
        supplier.offset_subconto,
        awaits_invoice=True,
    )
    stock.post_document(cid, waiting)
    session.catalog.reload()  # its new cost item
    win.show_place(("purchases",))
    shot("8c0_purchases")
    win.open_inventory_document(waiting)
    shot("8c10_purchase_awaiting")
    win.show_place(("home",))
    shot("0_home_awaiting")  # «Bu gün» reminds of it
    win.show_place(("sales",))
    shot("8c0_sales")
    from modern_gl.application.eqaime import parse_invoice
    from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog

    sample = {  # the shape of the portal's answer (etaxes-ext docs/api-reference.md)
        "id": "1",
        "serialNumber": "MT2603000111",
        "createdAt": "2026-03-05T10:00:00",
        "kind": "defaultInvoice",
        "sender": {
            "tin": "1700000001",
            "name": '"KOMPYUTER DÜNYASI" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ',
        },
        "items": [
            {
                "productName": i18n.tr("Бумага офисная А4"),
                "productGroup": {"code": "4802569000"},
                "unit": "qutu",
                "quantity": 20,
                "cost": 200,
                "vat18": 200,
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
    alfa = supplier.offset_subconto[0]  # renamed on the portal since the last import
    assert alfa is not None
    ledger.set_subconto_value_tax(cid, alfa, "1500000005")
    ledger.set_subconto_value_legal_name(cid, alfa, '"ALFA TREYD" MMC')
    renamed = {
        **sample,
        "serialNumber": "MT2603000222",
        "createdAt": "2026-03-12T10:00:00",
        "sender": {"tin": "1500000005", "name": '"ALFA TREYD GROUP" MMC'},
    }
    importer = EqaimeImportDialog(session, win)
    importer.company.setText("Portal: DEMO MMC · VÖEN 1402375141")
    importer.show_invoices(
        [
            parse_invoice(sample, sample, outgoing=False),
            parse_invoice(renamed, renamed, outgoing=False),
            parse_invoice(
                {
                    **sample,
                    "serialNumber": "MT2602004571",
                    "receiver": {"tin": "", "name": "Beta Servis"},
                },
                {
                    **sample,
                    "serialNumber": "MT2602004571",
                    "sender": None,
                    "receiver": {"tin": "", "name": "Beta Servis"},
                },
                outgoing=True,
            ),
        ]
    )
    importer.resize(1180, 860)
    importer.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    importer.grab().save(str(out / "8c10_eqaime_import.png"))
    importer.close()
    shoot_reconciliation(session, win, out)
    picker = cost_source_picker(session, None, win)
    picker.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    picker.grab().save(str(out / "8c5_cost_source_picker.png"))
    picker.close()
    win.show_place(("templates",))
    shot("8d_templates")
    from modern_gl.application.queries import list_templates

    sale = list_templates(session.conn, session.company_id)[0]
    sale = next(
        (t for t in list_templates(session.conn, session.company_id) if len(t.lines) == 2), sale
    )
    win.open_template(sale.id)
    shot("8e_template_editor")
    win.close_current()
    win.show_place(("templates",))
    win.new_document(entry=sale)
    page = cast(DocumentPage, win.stack.currentWidget())
    page.amount.setText("1180")
    page.amount.textEdited.emit("1180")
    shot("8f_document_from_template")
    from modern_gl.desktop.account_dialog import AccountDialog

    dialog = AccountDialog(session, session.catalog.by_code["02"], parent=win)
    dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    dialog.grab().save(str(out / "9_account_dialog.png"))
    dialog.close()
    dialog = AccountDialog(session, session.catalog.by_code["60"], parent=win)
    dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    dialog.grab().save(str(out / "9b_account_dialog_60.png"))
    dialog.account_type.showPopup()  # the type list, grouped by class
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    dialog.account_type.view().window().grab().save(str(out / "9c_account_types.png"))
    dialog.account_type.hidePopup()
    dialog.close()
    from modern_gl.desktop.period_dialog import PeriodDialog

    period = PeriodDialog(session, win)  # «Закрытие периода» (D95)
    period.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    period.grab().save(str(out / "16_period_dialog.png"))
    period.close()
    from modern_gl.application.history import document_history
    from modern_gl.desktop.history_dialog import HistoryDialog

    first = session.conn.execute(
        "SELECT id, number FROM documents WHERE company_id = ? ORDER BY id LIMIT 1",
        (session.company_id,),
    ).fetchone()
    story = HistoryDialog(  # «История изменений» (D96)
        f"№{first['number']}", document_history(session.conn, session.company_id, first["id"]), win
    )
    story.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    story.grab().save(str(out / "17_history_dialog.png"))
    story.close()
    from modern_gl.desktop.backups_dialog import BackupsDialog

    assert win.conn is not None and win.company_path is not None
    copies = BackupsDialog(win.workspace, win.conn, win.company_path, None, win)  # D97
    copies.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    copies.grab().save(str(out / "18_backups_dialog.png"))
    copies.close()

    # Currencies: a USD bank account, CBAR-like rates, a payment in USD, revaluation.
    from modern_gl.application.ledger import PostingInput
    from modern_gl.desktop.currencies_page import CurrenciesPage
    from modern_gl.domain.currency import parse_rate

    cid = session.company_id
    usd = ledger.currency_id(cid, "USD")
    usd_bank = ledger.add_subconto_value(cid, banks, "Kapital Bank USD")
    ledger.set_subconto_value_currency(cid, usd_bank, usd)
    for day, rate in (("2026-02-02", "1.7"), ("2026-02-16", "1.7025"), ("2026-02-27", "1.705")):
        ledger.set_rate(cid, "USD", day, parse_rate(rate), source="cbar")
    ledger.set_rate(cid, "EUR", "2026-02-27", parse_rate("1.9845"), source="cbar")
    acc = session.catalog.by_code
    azn_bank = next(v.id for v in session.catalog.values(banks) if v.currency_id is None)
    ledger.post_new(
        cid,
        "2026-02-05",
        [PostingInput(acc["52"].id, acc["51"].id, "850", (usd_bank,), (azn_bank,), "", usd, "500")],
        i18n.tr("Покупка валюты"),
    )
    session.catalog.reload()
    win.show_place(("currencies",))
    currencies = cast(CurrenciesPage, win.stack.currentWidget())
    currencies.refresh(select=usd)
    shot("10_currencies")
    win.new_document()
    page = cast(DocumentPage, win.stack.currentWidget())
    page.memo.setText(i18n.tr("Оплата поставщику"))
    m = page.model
    m.setData(m.index(0, 0), acc["60"].id)
    m.setData(m.index(0, 4), acc["52"].id)
    m.setData(m.index(0, 5), usd_bank)
    from modern_gl.desktop.postings import CURRENCY_AMOUNT

    m.setData(m.index(0, CURRENCY_AMOUNT), 30_000)
    shot("10b_document_currency")
    page.dirty = False
    win.close_current()
    # 60 in dollars on a day without its own rate: the note offers the Central Bank's
    session.working_date = date(2026, 3, 10)
    win.new_document()
    page = cast(DocumentPage, win.stack.currentWidget())
    page.memo.setText("Hosting")
    m = page.model
    m.setData(m.index(0, 0), acc["26"].id)
    m.setData(m.index(0, 1), next(iter(session.catalog.values(acc["26"].sc_kinds[0]))).id)
    m.setData(m.index(0, 4), acc["60"].id)
    m.setData(m.index(0, 11), m.parse(0, 11, "500 USD"))
    shot("10e_document_rate_note")
    page.dirty = False
    win.close_current()
    # Currency conversion (D37): 57 and 80 of the classic chart
    from modern_gl.desktop.conversion_page import ConversionPage

    session.working_date = date(2026, 2, 27)
    win.new_conversion()
    conversion = cast(ConversionPage, win.stack.currentWidget())
    for panel, value, amount in (
        (conversion.source, usd_bank, "300"),
        (conversion.target, azn_bank, "509.40"),
    ):
        box = panel.sc[0]
        box.setCurrentIndex(box.findData(value))
        panel._subconto_changed()
        panel.amount.setText(amount)
    conversion.add_fee().amount.setText("1")
    conversion.add_fee().set_place(acc["51"].id, (azn_bank,))
    conversion.fee_rows[1].amount.setText("0.50")
    conversion._changed()
    shot("10f_conversion")
    conversion.save(post=True)
    shot("10g_conversion_posted")
    win.close_current()
    session.working_date = date(2026, 2, 28)
    ledger.revalue(cid, "2026-02-28", "80")
    win.show_place(("osv",))
    osv = cast(OsvPage, win.pages[("osv",)])
    osv.in_currency.setVisible(True)
    osv.in_currency.setChecked(True)
    shot("10c_osv_currency")
    win.open_report("card", acc["52"].id, osv.params)
    shot("10d_card_currency")
    win.show_place(("invoices",))
    shot("11_invoices")
    win.open_report("card", acc["62"].id, osv.params)
    shot("11b_card_invoice")
    # The bank module (D47): bank accounts and the statement; a payment to a supplier
    from modern_gl.desktop.bank_operation_page import BankOperationPage
    from modern_gl.desktop.bank_page import BankPage

    win.show_place(("bank",))
    bank = cast(BankPage, win.pages[("bank",)])
    # D78: the accounts by group (a business card too), the statements, one statement
    ledger.bank.add_bank_account(session.company_id, "ABB Visa", "51", "card", card_digits="4417")
    session.catalog.reload()
    bank.refresh()
    shot("12_bank")
    from modern_gl.desktop.bank_page.dialogs import BankAccountDialog

    card_dialog = BankAccountDialog(session, None, win)
    card_dialog.name.setText("Kapital Mastercard")
    card_dialog.kind.setCurrentIndex(card_dialog.kind.findData("card"))
    card_dialog.digits.setText("0921")
    card_dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    card_dialog.grab().save(str(out / "12_bank_card_dialog.png"))
    card_dialog.close()
    first = next(r for r in bank.model.rows if hasattr(r, "place"))
    bank.open_account(first.place.key)
    oldest = bank.statements[0]
    ledger.bank.set_bank_closing(
        session.company_id,
        first.place.account_id,
        first.place.value_id,
        oldest.date_from,
        oldest.date_to,
        oldest.closing,
    )
    bank.refresh()
    shot("12a_bank_statements")
    bank.drill(bank.model.rows[0])
    shot("12a2_bank_statement")
    line = bank.entry  # a line of the bank's statement typed in: who, which account, how much
    line.counterparty_box.setCurrentIndex(0)
    line.counterparty_chosen()
    line.money_out.setText("120.00")
    line.money_out.setFocus()
    shot("12a3_bank_entry")
    line.clear()
    bank.new_operation("out")
    payment = cast(BankOperationPage, win.stack.currentWidget())
    payment.counterparty_edit.setText(i18n.tr("Альфа Трейд"))
    payment.counterparty_edit.editingFinished.emit()
    payment.amount.setText("590")
    payment.amount.textEdited.emit("590")
    payment.invoice.setText("MT2602000777")
    payment.invoice.textEdited.emit("MT2602000777")
    shot("12b_bank_payment")  # one line, folded: who, e-qaimə, amount
    payment.add_fee()
    payment.line_rows[1].amount.setText("1.20")
    payment._changed()
    shot("12b2_bank_payment_lines")
    win.notify(i18n.tr("Документ №{n} проведён", n=14), lambda: None)
    shot("15_toast")  # what was done, at the bottom, with «Undo» (D86)
    shoot_vat_deposit(session, win, ledger, shot)
    shoot_sale_groups(session, win, ledger, shot)
    shoot_stock_only(win, ledger, shot)
    shoot_viewing(win, shot)


def shoot_stock_only(win, ledger, shot) -> None:
    """D90: the same company kept as a warehouse only — the books are not shown."""
    from modern_gl.domain.company import FULL, STOCK_ONLY

    win._confirm_close_all = lambda: True  # the bank payment above is left unsaved
    ledger.set_company_mode(win.open_session.company_id, STOCK_ONLY)
    win.open_company(win.company_path)
    win.open_session.working_date = date(2026, 2, 28)
    shot("14_stock_only")
    win.new_inventory_document("receipt")
    shot("14b_stock_only_purchase")
    win.open_session.ledger.set_company_mode(win.open_session.company_id, FULL)
    win.open_company(win.company_path)


def shoot_viewing(win, shot) -> None:
    """D80: the same company open for viewing only — nothing offers to change it."""
    win._confirm_close_all = lambda: True  # the bank payment above is left unsaved
    win.view_company(win.company_path)
    s = win.open_session
    s.working_date = date(2026, 2, 28)
    win.show_place(("journal",))
    shot("13_viewing_journal")
    journal = cast(JournalPage, win.pages[("journal",)])
    journal.table.selectRow(2)
    win.open_document(journal.model.docs[2].id)
    shot("13b_viewing_document")
    win.show_place(("purchases",))
    shot("13c_viewing_purchases")
    win.show_place(("bank",))
    shot("13d_viewing_bank")


def shoot_vat_deposit(session, win, ledger, shot) -> None:
    """D69: Alfa's MT2601001842 (1 200.00 + ƏDV 216.00) paid from the bank and the ƏDV
    deposit account (55, with money on it) in one form."""
    from modern_gl.application.ledger import PostingInput
    from modern_gl.desktop.bank_operation_page import BankOperationPage
    from modern_gl.desktop.bank_page import BankPage

    cid, catalog = session.company_id, session.catalog
    banks = catalog.by_code["51"].sc_kinds[0]
    assert banks is not None
    ledger.add_account(
        cid, "55", i18n.tr("Депозитный счёт НДС"), account_type="vat_deposit", subconto=[banks]
    )
    catalog.reload()
    deposit = ledger.add_subconto_value(cid, banks, "ƏDV depozit")
    deposit_account, capital = catalog.by_code["55"].id, catalog.by_code["80"].id
    ledger.post_new(
        cid, "2026-02-01", [PostingInput(deposit_account, capital, "2000", [deposit], [])]
    )
    catalog.reload()
    bank = cast(BankPage, win.pages[("bank",)])
    win.show_place(("bank",))
    bank.refresh()
    bank.new_operation("out")
    payment = cast(BankOperationPage, win.stack.currentWidget())
    payment.counterparty_edit.setText(i18n.tr("Альфа Трейд"))
    payment.counterparty_edit.editingFinished.emit()
    index = next(
        i
        for i in range(payment.invoice.count())
        if payment.invoice.itemText(i).startswith("MT2601001842")
    )
    payment.invoice.setCurrentIndex(index)
    payment.invoice.activated.emit(index)
    shot("12b3_bank_vat_deposit")


def shoot_sale_groups(session, win, ledger, shot) -> None:
    """Sales groups on 46 (D61): the sale asks for the group in its own column."""
    cid = session.company_id
    groups = ledger.add_subconto_kind(cid, None, "Satış qrupları")
    goods = ledger.add_subconto_value(cid, groups, "Mallar")
    services = ledger.add_subconto_value(cid, groups, "Xidmətlər")
    ledger.update_account(cid, "46", subconto=[groups])
    session.catalog.reload()
    win.new_inventory_document("sale")
    sale_page = cast(InventoryDocumentPage, win.stack.currentWidget())
    lines = sale_page.model
    customer = session.catalog.values(ledger.subconto_kind_id(cid, "counterparty"))[0].id
    for row, (memo, amount, group) in enumerate(
        [("Konsultasiya", 50_000, services), ("Çatdırılma", 12_000, goods)]
    ):
        if row:
            lines.insert_row()
        for key, value in (("memo", memo), ("amount", amount), ("sale1", group), ("sc1", customer)):
            lines.setData(lines.index(row, lines.columns.index(key)), value)
    sale_page.table.configure_columns()
    shot("12c_sale_groups")


def shoot_reconciliation(session, win, out: Path) -> None:
    """«Сверка с порталом» over the demo's purchases: one e-qaimə agrees, one differs in
    amount, two are only on the portal, one is cancelled there (D53)."""
    from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
    from modern_gl.domain.eqaime import ON_APPROVAL, PortalInvoice
    from modern_gl.domain.periods import month_bounds
    from modern_gl.reporting.eqaime_reconciliation import book_invoices, reconcile

    books = sorted(
        book_invoices(session.conn, session.company_id, False).values(), key=lambda b: b.doc_date
    )
    month = books[0].doc_date[:7] if books else f"{session.working_date:%Y-%m}"
    first, last = month_bounds(month)
    day = first.isoformat()
    portal = [
        PortalInvoice(
            b.number,
            False,
            b.doc_date,
            "approved",
            "1700000001",
            "",
            b.total + (11_800 if n == 1 else 0),
            b.vat + (1_800 if n == 1 else 0),
        )
        for n, b in enumerate(books[:3])
        if b.doc_date[:7] == month
    ]
    portal += [
        PortalInvoice(
            "MT2603000777",
            False,
            day,
            "approved",
            "1700000001",
            "KOMPYUTER DÜNYASI MMC",
            23_600,
            3_600,
        ),
        PortalInvoice(
            "MT2603000801",
            False,
            last.isoformat(),
            ON_APPROVAL,
            "1500000005",
            "ALFA TREYD MMC",
            47_200,
            7_200,
        ),
    ]
    dialog = EqaimeReconciliationDialog(session, win)
    dialog.company.setText("Portal: DEMO MMC · VÖEN 1402375141")
    dialog.period_field.set_period(first, last)
    dialog.show_result(reconcile(session.conn, session.company_id, False, first, last, portal))
    dialog.resize(1180, 760)
    dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    dialog.grab().save(str(out / "8c11_eqaime_reconciliation.png"))
    dialog.period_field.show_presets()  # ▾: the portal's usual periods (D105)
    dialog.period_field.window_shown.grab().save(str(out / "8c12_eqaime_period_window.png"))
    dialog.close()


if __name__ == "__main__":
    main()
