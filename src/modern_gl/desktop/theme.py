"""Visual language: calm, light, airy (inspired by Things), dense where it matters.

All colors and fonts live here as tokens; widgets never hardcode them.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    window: str = "#FFFFFF"
    sidebar: str = "#F5F6F8"
    surface: str = "#FFFFFF"
    subtle: str = "#F7F8FA"  # hover, zebra, input wells
    hairline: str = "#E8EAED"
    text: str = "#1D2025"
    secondary: str = "#6B7280"
    tertiary: str = "#A0A6AF"
    accent: str = "#2D6BE4"
    accent_hover: str = "#255DCB"
    accent_soft: str = "#E8F0FD"
    selection: str = "#E3EBFA"
    sidebar_selection: str = "#E2E6ED"
    green: str = "#2E9E62"
    green_soft: str = "#E6F5EC"
    amber: str = "#C98A1B"
    amber_soft: str = "#FCF3E1"
    red: str = "#DC4446"
    red_soft: str = "#FCE9E9"
    violet: str = "#7C5CD6"
    teal: str = "#1F9BA6"


P = Palette()


def _family(*candidates: str) -> str:
    available = set(QFontDatabase.families())
    return next((f for f in candidates if f in available), "Sans Serif")


class Fonts:
    """Created after QApplication exists."""

    def __init__(self) -> None:
        text = _family("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue")
        display = _family("Segoe UI Variable Display", "Segoe UI Semibold", text)
        self.text_family = text
        self.body = QFont(text, 10)
        self.small = QFont(text, 9)
        self.caption = QFont(text, 8)
        self.caption.setWeight(QFont.Weight.DemiBold)
        self.caption.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        self.title = QFont(display, 20)
        self.title.setWeight(QFont.Weight.DemiBold)
        self.heading = QFont(display, 13)
        self.heading.setWeight(QFont.Weight.DemiBold)
        self.total = QFont(display, 15)
        self.total.setWeight(QFont.Weight.DemiBold)
        self.bold = QFont(self.body)
        self.bold.setWeight(QFont.Weight.DemiBold)


FONTS: Fonts | None = None


def fonts() -> Fonts:
    global FONTS
    if FONTS is None:
        FONTS = Fonts()
    return FONTS


def dot_icon(color: str, size: int = 18, glyph: str = "") -> QIcon:
    """A soft rounded square with an optional white glyph — sidebar icons."""
    pm = QPixmap(size * 2, size * 2)  # 2x for HiDPI
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), 5, 5)
    if glyph:
        p.setPen(QColor("#FFFFFF"))
        f = QFont(fonts().text_family, 8)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Mode.Selected)  # keep full color when the item is selected
    return icon


STYLESHEET = f"""
* {{ outline: 0; }}
QMainWindow, QWidget#page {{ background: {P.window}; }}
QToolTip {{
    background: {P.text}; color: #FFFFFF; border: none; padding: 5px 8px; border-radius: 6px;
}}

/* Sidebar */
QWidget#sidebar {{ background: {P.sidebar}; border-right: 1px solid {P.hairline}; }}
QListWidget#nav {{ background: transparent; border: none; }}
QListWidget#nav::item {{
    color: {P.text}; padding: 6px 8px; margin: 1px 10px; border-radius: 7px;
}}
QListWidget#nav::item:hover {{ background: #ECEEF2; }}
QListWidget#nav::item:selected {{ background: {P.sidebar_selection}; color: {P.text}; }}
QListWidget#nav::item:disabled {{ color: {P.tertiary}; background: transparent; }}
QPushButton#company {{
    text-align: left; padding: 10px 12px; margin: 14px 10px 8px 10px; border: none;
    border-radius: 8px; color: {P.text}; background: transparent;
}}
QPushButton#company:hover {{ background: #ECEEF2; }}
QPushButton#company::menu-indicator {{ image: none; }}

/* Buttons */
QPushButton {{
    background: {P.surface}; color: {P.text}; border: 1px solid {P.hairline};
    border-radius: 7px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {P.subtle}; }}
QPushButton:disabled {{ color: {P.tertiary}; }}
QPushButton#primary {{
    background: {P.accent}; color: #FFFFFF; border: 1px solid {P.accent}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {P.accent_hover}; }}
QPushButton#flat {{ background: transparent; border: none; color: {P.accent}; padding: 6px 8px; }}
QPushButton#flat:hover {{ background: {P.accent_soft}; }}
QPushButton#danger {{ background: transparent; border: none; color: {P.red}; padding: 6px 8px; }}
QPushButton#danger:hover {{ background: {P.red_soft}; }}
QPushButton#dangerSolid {{
    background: {P.red}; color: #FFFFFF; border: 1px solid {P.red}; font-weight: 600;
}}
QPushButton#dangerSolid:disabled {{
    background: {P.red_soft}; border: 1px solid {P.red_soft}; color: #FFFFFF;
}}
QPushButton#fab {{
    background: {P.accent}; color: #FFFFFF; border: none; border-radius: 26px;
    font-size: 22pt; padding: 0 0 4px 0;
}}
QPushButton#fab:hover {{ background: {P.accent_hover}; }}

/* Inputs */
QLineEdit, QDateEdit, QComboBox {{
    background: {P.subtle}; border: 1px solid transparent; border-radius: 7px;
    padding: 5px 8px; color: {P.text}; selection-background-color: {P.accent};
}}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{
    background: {P.surface}; border: 1px solid {P.accent};
}}
QLineEdit#titleEdit {{
    background: transparent; border: none; padding: 0; color: {P.text};
}}
QLineEdit#search {{ padding-left: 10px; min-width: 320px; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 8px;
    selection-background-color: {P.selection}; selection-color: {P.text}; padding: 4px;
}}

/* Tables */
QTableView {{
    background: {P.surface}; border: none; gridline-color: transparent;
    selection-background-color: {P.selection}; selection-color: {P.text};
}}
QTableView::item {{ border-bottom: 1px solid {P.hairline}; padding: 0 8px; }}
QTableView::item:hover {{ background: {P.subtle}; }}
QTableView::item:selected {{ background: {P.selection}; color: {P.text}; }}
QTableView QLineEdit {{
    background: {P.surface}; border: 1px solid {P.accent}; border-radius: 4px; padding: 0 6px;
}}
QHeaderView {{ background: {P.surface}; border: none; }}
QHeaderView::section {{
    background: {P.surface}; color: {P.tertiary}; border: none;
    border-bottom: 1px solid {P.hairline}; padding: 6px 8px;
}}
QHeaderView::section:vertical {{
    color: {P.tertiary}; border: none; border-bottom: 1px solid {P.hairline}; padding: 0 6px;
}}
QTableCornerButton::section {{ background: {P.surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D5D9DF; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #BCC2CA; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D5D9DF; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QListView#completer {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 10px;
    padding: 4px; outline: 0;
}}
QListView#completer::item {{ padding: 6px 10px; border-radius: 6px; color: {P.text}; }}
QListView#completer::item:hover {{ background: {P.subtle}; }}
QListView#completer::item:selected {{ background: {P.selection}; color: {P.text}; }}
QCheckBox {{ color: {P.secondary}; spacing: 8px; }}

QMenu {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; color: {P.text}; }}
QMenu::item:selected {{ background: {P.selection}; }}
QMenu::separator {{ height: 1px; background: {P.hairline}; margin: 4px 8px; }}

QStatusBar {{ background: {P.window}; color: {P.secondary}; border-top: 1px solid {P.hairline}; }}
QLabel#secondary {{ color: {P.secondary}; }}
QLabel#tertiary {{ color: {P.tertiary}; }}
QLabel#error {{
    color: {P.red}; background: {P.red_soft}; border-radius: 7px; padding: 7px 10px;
}}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    f = fonts()
    app.setFont(f.body)
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(P.window))
    pal.setColor(QPalette.ColorRole.Base, QColor(P.surface))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(P.subtle))
    pal.setColor(QPalette.ColorRole.Text, QColor(P.text))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(P.text))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(P.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(P.selection))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(P.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(P.tertiary))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
