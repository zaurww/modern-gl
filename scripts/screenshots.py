"""Render the main screens of the demo company to PNG (for design review).

uv run python scripts/screenshots.py [out_dir] [az|ru]
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
from modern_gl.desktop import qt_texts, theme
from modern_gl.desktop.app import add_demo_company
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.opening_balances_page import OpeningBalancesPage
from modern_gl.desktop.reports_page import OsvPage
from modern_gl.infrastructure.workspace import Workspace


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    i18n.set_language(sys.argv[2] if len(sys.argv) > 2 else "az")
    app = QApplication(sys.argv)
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
                if w.objectName() == "completer" and w.isVisible()
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
    win.show_place(("opening",))
    opening = cast(OpeningBalancesPage, win.pages[("opening",)])
    opening.debit_model.setData(opening.debit_model.index(0, 0), session.catalog.by_code["50"].id)
    opening.debit_model.setData(opening.debit_model.index(0, 11), 175_000)
    opening.credit_model.setData(opening.credit_model.index(0, 4), session.catalog.by_code["85"].id)
    opening.credit_model.setData(opening.credit_model.index(0, 11), 175_000)
    shot("5e_opening_balances")
    win.open_report("subconto", session.catalog.by_code["60"].id, osv.params)
    shot("6_subconto")
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
    partners = session.catalog.owner_kinds[contracts]
    for i, v in enumerate(session.catalog.values(partners)):  # VÖEN of the demo partners
        ledger.set_subconto_value_tax(session.company_id, v.id, f"{1400057421 + i * 1111}")
    acme = ledger.add_subconto_value(session.company_id, partners, "Acme Trading GmbH")
    ledger.set_subconto_value_tax(
        session.company_id, acme, "DE 811 234 567", nonresident=True, country="Almaniya"
    )
    session.catalog.reload()
    directories.refresh(select_kind=partners)
    shot("8b5_counterparties")
    for name, value in (
        ("8b6_counterparty_dialog", session.catalog.values(partners)[1]),
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
    win.show_place(("inventory",))
    inventory = cast(InventoryPage, win.stack.currentWidget())
    inventory.refresh()
    shot("8c_inventory")
    inventory_document = min(  # the first one, with VAT
        (row for row in inventory.documents_model.rows if row.doc_type == "receipt"),
        key=lambda row: row.number,
    )
    win.open_inventory_document(inventory_document.id)
    assert isinstance(win.stack.currentWidget(), InventoryDocumentPage)
    shot("8c2_inventory_document")
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


if __name__ == "__main__":
    main()
