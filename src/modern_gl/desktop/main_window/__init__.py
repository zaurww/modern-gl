"""Main window: Things-like sidebar (company, places, open items) + one page at a time."""

from modern_gl.desktop.main_window.company_files import CompanyFiles, confirm_delete
from modern_gl.desktop.main_window.sidebar import PLACE_KEYS, NavDelegate, Sidebar
from modern_gl.desktop.main_window.window import MainWindow

__all__ = ["PLACE_KEYS", "CompanyFiles", "MainWindow", "NavDelegate", "Sidebar", "confirm_delete"]
