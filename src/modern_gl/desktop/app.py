"""Entry point:  uv run modern-gl [path\\to\\ledger.db] [--demo]

--demo fills an empty database with a demo company.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from modern_gl import i18n
from modern_gl.application.queries import list_companies
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.infrastructure.db import connect

DEFAULT_DB = Path.home() / "ModernGL" / "ledger.db"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Modern GL")
    app.setOrganizationName("ModernGL")
    theme.apply(app)
    settings = QSettings()
    lang = str(settings.value("language", i18n.DEFAULT))
    i18n.set_language(lang if lang in i18n.LANGUAGES else i18n.DEFAULT)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    window = MainWindow(conn, settings)
    if "--demo" in sys.argv and not list_companies(conn):
        create_demo_company(window.ledger)
    if not window.start():
        return 0
    window.show()
    code = app.exec()
    conn.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
