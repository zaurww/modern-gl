"""Entry point:  uv run modern-gl [--data FOLDER] [--demo] [--demo-year] [--demo-years]

Each company is one file in the data folder (default: Documents\\Modern GL).
--data       use another folder (remembered for next time)
--demo       add a demo company when the folder has none
--demo-year  add the company with the whole year 2026 of work, unless it is there
--demo-years the same company with two years of work, 2025 and 2026
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from modern_gl import demo_year, i18n
from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import crash_dialog, qt_texts, theme
from modern_gl.desktop.cell_editing import select_whole_on_entry
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.preferences import (
    COMPANY_FILES,
    DATA_DIR,
    LANGUAGE,
    MIRROR_SETTING,
    THEME,
    prefs,
)
from modern_gl.infrastructure import logs
from modern_gl.infrastructure.db import connect


def default_folder() -> Path:
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(documents or Path.home()) / "Modern GL"


def add_demo_company(workspace: Workspace, years: tuple[int, ...] = ()) -> Path:
    """The small demo company, or with `years` the one with those whole years of work."""
    name = year_demo_name(years) if years else i18n.tr("ДЕМО ООО")
    path = workspace.new_path(name)
    conn = connect(path)
    try:
        if years:
            demo_year.create_year_demo(Ledger(conn), name, years)
        else:
            create_demo_company(Ledger(conn))
    finally:
        conn.close()
    return path


def year_demo_name(years: tuple[int, ...]) -> str:
    return demo_year.TWO_YEARS_NAME if years == demo_year.TWO_YEARS else demo_year.NAME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Modern GL")
    app.setOrganizationName("ModernGL")
    crash_dialog.install()  # before anything else can fail
    remembered = prefs()
    theme.use_theme(remembered.text(THEME, theme.DEFAULT_THEME))
    theme.apply(app)
    qt_texts.install(app)
    select_whole_on_entry(app)
    lang = remembered.text(LANGUAGE, i18n.DEFAULT)
    i18n.set_language(lang if lang in i18n.LANGUAGES else i18n.DEFAULT)

    args = sys.argv[1:]
    if "--data" in args and args.index("--data") + 1 < len(args):
        remembered.set(DATA_DIR, args[args.index("--data") + 1])
    folder = Path(remembered.text(DATA_DIR) or default_folder())
    logs.start(folder)
    files = remembered.texts(COMPANY_FILES)
    mirror = remembered.text(MIRROR_SETTING)
    workspace = Workspace(folder, files, mirror or None)
    if "--demo" in args and not workspace.companies():
        add_demo_company(workspace)
    for flag, years in (("--demo-year", (demo_year.YEAR,)), ("--demo-years", demo_year.TWO_YEARS)):
        name = year_demo_name(years)
        if flag in args and all(c.name != name for c in workspace.companies()):
            add_demo_company(workspace, years)

    window = MainWindow(workspace, remembered.store)
    if not window.start():
        return 0
    window.show()
    code = app.exec()
    window.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
