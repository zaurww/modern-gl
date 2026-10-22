"""Entry point:  uv run modern-gl [--data FOLDER] [--demo] [--demo-year]

Each company is one file in the data folder (default: Documents\\Modern GL).
--data       use another folder (remembered for next time)
--demo       add a demo company when the folder has none
--demo-year  add the company with the whole year 2026 of work, unless it is there
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication

from modern_gl import demo_year, i18n
from modern_gl.application.ledger import Ledger
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import qt_texts, theme
from modern_gl.desktop.cell_editing import select_whole_on_entry
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import Workspace


def default_folder() -> Path:
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(documents or Path.home()) / "Modern GL"


def add_demo_company(workspace: Workspace, year: bool = False) -> Path:
    """The small demo company, or with `year` the one with the whole year 2026."""
    path = workspace.new_path(demo_year.NAME if year else i18n.tr("ДЕМО ООО"))
    conn = connect(path)
    try:
        if year:
            demo_year.create_year_demo(Ledger(conn))
        else:
            create_demo_company(Ledger(conn))
    finally:
        conn.close()
    return path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Modern GL")
    app.setOrganizationName("ModernGL")
    settings = QSettings()
    theme.set_theme(str(settings.value("theme", theme.DEFAULT_THEME)))
    theme.apply(app)
    qt_texts.install(app)
    select_whole_on_entry(app)
    lang = str(settings.value("language", i18n.DEFAULT))
    i18n.set_language(lang if lang in i18n.LANGUAGES else i18n.DEFAULT)

    args = sys.argv[1:]
    if "--data" in args and args.index("--data") + 1 < len(args):
        settings.setValue("data_dir", args[args.index("--data") + 1])
    folder = Path(str(settings.value("data_dir", "") or default_folder()))
    files = cast(list[str], settings.value("company_files", [], type=list))
    workspace = Workspace(folder, files)
    if "--demo" in args and not workspace.companies():
        add_demo_company(workspace)
    if "--demo-year" in args and all(c.name != demo_year.NAME for c in workspace.companies()):
        add_demo_company(workspace, year=True)

    window = MainWindow(workspace, settings)
    if not window.start():
        return 0
    window.show()
    code = app.exec()
    window.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
