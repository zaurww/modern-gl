"""Render the main screens of the demo company to PNG (for design review).

uv run python scripts/screenshots.py [out_dir] [az|ru]
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":  # the offscreen platform doesn't see system fonts by itself
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modern_gl import i18n  # noqa: E402
from modern_gl.desktop import theme  # noqa: E402
from modern_gl.desktop.app import add_demo_company  # noqa: E402
from modern_gl.desktop.main_window import MainWindow  # noqa: E402
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
    win.session.working_date = date(2026, 2, 28)
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
    docs = win.pages[("journal",)].model.docs
    win.open_document(next(d.id for d in docs if len(d.memo) and d.lines == 2))
    shot("2_document_posted")
    win.open_document(next(d.id for d in docs if d.status == "draft"))
    shot("3_document_draft")
    win.new_document()
    page = win.stack.currentWidget()
    cat = win.session.catalog
    page.memo.setText(i18n.tr("Аренда за март"))
    page.model.setData(page.model.index(0, 0), cat.by_code["26"].id)
    page.model.setData(page.model.index(0, 4), cat.by_code["60.1"].id)
    shot("4_document_new")
    idx = page.model.index(0, 5)
    page.table.setCurrentIndex(idx)
    page.table.edit(idx)
    shot("4b_subconto_list")
    page.table.setFocus()
    win.show_place(("osv",))
    shot("5_osv")
    win.pages[("osv",)].top_only.setChecked(True)
    shot("5b_osv_top_only")
    win.pages[("osv",)].top_only.setChecked(False)
    win.pages[("osv",)].sections.setChecked(True)
    shot("5c_osv_sections")
    win.pages[("osv",)].sections.setChecked(False)
    win.pages[("osv",)].expand.setChecked(True)
    shot("5d_osv_expanded")
    win.pages[("osv",)].expand.setChecked(False)
    osv = win.pages[("osv",)]
    win.open_report("subconto", "60.1", osv.params)
    shot("6_subconto")
    win.open_report("card", "51", osv.params)
    shot("7_card")
    win.show_place(("chart",))
    shot("8_chart")
    win.show_place(("directories",))
    directories = win.stack.currentWidget()
    banks = win.session.catalog.by_code["51"].sc_kinds[0]
    for name in ("Kapital Bank", "ABB"):
        win.ledger.add_subconto_value(win.session.company_id, banks, name)
    win.session.catalog.reload()
    directories.refresh(select_kind=banks)
    shot("8b_directories")
    from modern_gl.desktop.account_dialog import AccountDialog

    dialog = AccountDialog(win.session, win.session.catalog.by_code["02"], parent=win)
    dialog.show()
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()
    dialog.grab().save(str(out / "9_account_dialog.png"))


if __name__ == "__main__":
    main()
