"""Render the main screens of the demo company to PNG (for design review).

uv run python scripts/screenshots.py [out_dir]
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":  # the offscreen platform doesn't see system fonts by itself
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ["WINDIR"], "Fonts"))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modern_gl.demo_data import create_demo_company  # noqa: E402
from modern_gl.desktop import theme  # noqa: E402
from modern_gl.desktop.main_window import MainWindow  # noqa: E402
from modern_gl.infrastructure.db import connect  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    theme.apply(app)
    conn = connect(":memory:")
    win = MainWindow(conn)
    create_demo_company(win.ledger)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.resize(1400, 860)
    win.show()

    def shot(name: str) -> None:
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)  # let the page fade-in finish
        loop.exec()
        win.grab().save(str(out / f"{name}.png"))
        print(out / f"{name}.png")

    shot("1_journal")
    docs = win.pages[("journal",)].model.docs
    win.open_document(next(d.id for d in docs if "Авансовый" in d.memo))
    shot("2_document_posted")
    win.open_document(next(d.id for d in docs if d.status == "draft"))
    shot("3_document_draft")
    win.new_document()
    shot("4_document_new")
    win.show_place(("osv",))
    shot("5_osv")
    osv = win.pages[("osv",)]
    win.open_report("subconto", "60.1", osv.params)
    shot("6_subconto")
    win.open_report("card", "51", osv.params)
    shot("7_card")
    win.show_place(("chart",))
    shot("8_chart")


if __name__ == "__main__":
    main()
