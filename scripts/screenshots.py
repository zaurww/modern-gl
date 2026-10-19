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

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modern_gl import i18n  # noqa: E402
from modern_gl.desktop import theme  # noqa: E402
from modern_gl.desktop.app import add_demo_company  # noqa: E402
from modern_gl.desktop.directories_page import DirectoriesPage  # noqa: E402
from modern_gl.desktop.document_page import DocumentPage  # noqa: E402
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage  # noqa: E402
from modern_gl.desktop.inventory_page import InventoryPage  # noqa: E402
from modern_gl.desktop.journal_page import JournalPage  # noqa: E402
from modern_gl.desktop.main_window import MainWindow  # noqa: E402
from modern_gl.desktop.reports_page import OsvPage  # noqa: E402
from modern_gl.infrastructure.workspace import Workspace  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    i18n.set_language(sys.argv[2] if len(sys.argv) > 2 else "az")
    app = QApplication(sys.argv)
    theme.apply(app)
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
    win.open_report("subconto", session.catalog.by_code["60"].id, osv.params)
    shot("6_subconto")
    win.open_report("card", session.catalog.by_code["51"].id, osv.params)
    shot("7_card")
    win.show_place(("chart",))
    shot("8_chart")
    win.show_place(("directories",))
    directories = cast(DirectoriesPage, win.stack.currentWidget())
    banks = session.catalog.by_code["51"].sc_kinds[0]
    assert banks is not None  # 51 has the "bank accounts" directory
    for name in ("Kapital Bank", "ABB"):
        ledger.add_subconto_value(session.company_id, banks, name)
    session.catalog.reload()
    directories.refresh(select_kind=banks)
    shot("8b_directories")
    win.show_place(("inventory",))
    inventory = cast(InventoryPage, win.stack.currentWidget())
    inventory.refresh()
    shot("8c_inventory")
    inventory_document = next(
        row for row in inventory.documents_model.rows if row["doc_type"] == "receipt"
    )
    win.open_inventory_document(inventory_document["id"])
    assert isinstance(win.stack.currentWidget(), InventoryDocumentPage)
    shot("8c2_inventory_document")
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
    ledger.revalue(cid, "2026-02-28", "80")
    win.show_place(("osv",))
    osv = cast(OsvPage, win.pages[("osv",)])
    osv.in_currency.setVisible(True)
    osv.in_currency.setChecked(True)
    shot("10c_osv_currency")
    win.open_report("card", acc["52"].id, osv.params)
    shot("10d_card_currency")


if __name__ == "__main__":
    main()
