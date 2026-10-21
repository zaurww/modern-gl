"""Visual language: calm, light, airy (inspired by Things), dense where it matters.

All colors and fonts live here as tokens; widgets never hardcode them.

Themes (THEMES) change some colors of the one palette; the user picks one in the
company menu. A new theme is one more entry there.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication


@dataclass
class Palette:
    """One object for the whole program: set_theme() changes it in place, so modules
    that imported P see the new colors."""

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
    field: str = "#F1F3F5"  # input wells: visible on white, quiet
    field_hover: str = "#EBEDF0"
    header_text: str = "#8A919B"  # column captions: quiet but readable
    canvas: str = "#FFFFFF"  # behind pages ("craft": grey under white sheets)
    sheet_border: str = "transparent"
    sheet_padding: str = "0"  # a sheet keeps its rows off its rounded edge
    sidebar_hover: str = "#ECEEF2"
    scrollbar: str = "#D5D9DF"
    scrollbar_hover: str = "#BCC2CA"
    on_accent: str = "#FFFFFF"  # text on accent, red buttons and icon squares
    tooltip: str = "#1D2025"
    tooltip_text: str = "#FFFFFF"


# name -> (title in the menu, the colors that differ from Palette)
THEMES: dict[str, tuple[str, dict[str, str]]] = {
    "things": ("Things — один белый лист", {}),
    "craft": (
        "Craft — серый фон, белые листы",
        {
            "window": "#F6F7F9",
            "canvas": "#F6F7F9",
            "sidebar": "#EEF0F3",
            "sidebar_selection": "#E1E4EA",
            "field": "#FFFFFF",
            "field_hover": "#FFFFFF",
            "sheet_border": "#E6E8EC",
            "sheet_padding": "0 6px",
        },
    ),
    # Popular editor palettes (catppuccin.com, rosepinetheme.com, nordtheme.com): their
    # own colors; soft tints are the color mixed into the background.
    "catppuccin_latte": (
        "Catppuccin Latte — тёплый кремовый",
        {
            "window": "#EFF1F5",
            "canvas": "#EFF1F5",
            "surface": "#EFF1F5",
            "sidebar": "#E6E9EF",
            "sidebar_hover": "#DFE3EA",
            "sidebar_selection": "#DCE0E8",
            "subtle": "#E6E9EF",
            "hairline": "#DCE0E8",
            "field": "#E6E9EF",
            "field_hover": "#DCE0E8",
            "text": "#4C4F69",
            "secondary": "#6C6F85",
            "tertiary": "#9CA0B0",
            "header_text": "#8C8FA1",
            "accent": "#1E66F5",
            "accent_hover": "#1A57D1",
            "accent_soft": "#DCE5F8",
            "selection": "#D5DFF5",
            "green": "#40A02B",
            "green_soft": "#DDEBDB",
            "amber": "#DF8E1D",
            "amber_soft": "#F3E6D6",
            "red": "#D20F39",
            "red_soft": "#F3DADF",
            "violet": "#8839EF",
            "teal": "#179299",
            "scrollbar": "#CCD0DA",
            "scrollbar_hover": "#ACB0BE",
            "tooltip": "#4C4F69",
            "tooltip_text": "#EFF1F5",
        },
    ),
    "rose_pine_dawn": (
        "Rosé Pine Dawn — мягкий бежевый",
        {
            "window": "#FAF4ED",
            "canvas": "#FAF4ED",
            "surface": "#FAF4ED",
            "sidebar": "#F2E9E1",
            "sidebar_hover": "#ECE2D9",
            "sidebar_selection": "#E4DBD5",
            "subtle": "#F4EDE8",
            "hairline": "#E8DFD8",
            "field": "#F2E9E1",
            "field_hover": "#ECE2D9",
            "text": "#575279",
            "secondary": "#797593",
            "tertiary": "#9893A5",
            "header_text": "#9893A5",
            "accent": "#286983",
            "accent_hover": "#215A71",
            "accent_soft": "#E0E6E4",
            "selection": "#DCE4E3",
            "green": "#56949F",
            "green_soft": "#E2EAE6",
            "amber": "#D7902A",
            "amber_soft": "#F7E8D3",
            "red": "#B4637A",
            "red_soft": "#F2E1DF",
            "violet": "#907AA9",
            "teal": "#56949F",
            "scrollbar": "#DFDAD9",
            "scrollbar_hover": "#CECACD",
            "tooltip": "#575279",
            "tooltip_text": "#FAF4ED",
        },
    ),
    "nord_light": (
        "Nord — холодный серо-голубой",
        {
            "window": "#ECEFF4",
            "canvas": "#ECEFF4",
            "surface": "#ECEFF4",
            "sidebar": "#E5E9F0",
            "sidebar_hover": "#DEE3EB",
            "sidebar_selection": "#D8DEE9",
            "subtle": "#E5E9F0",
            "hairline": "#D8DEE9",
            "field": "#E5E9F0",
            "field_hover": "#DEE3EB",
            "text": "#2E3440",
            "secondary": "#4C566A",
            "tertiary": "#8A93A5",
            "header_text": "#7B8598",
            "accent": "#5E81AC",
            "accent_hover": "#50729C",
            "accent_soft": "#DCE3EE",
            "selection": "#D5DEEA",
            "green": "#6E9459",
            "green_soft": "#E0E8DE",
            "amber": "#C08A2E",
            "amber_soft": "#F0E8DA",
            "red": "#BF616A",
            "red_soft": "#F0DEE1",
            "violet": "#B48EAD",
            "teal": "#6FA3A2",
            "scrollbar": "#D8DEE9",
            "scrollbar_hover": "#B9C2D0",
            "tooltip": "#3B4252",
            "tooltip_text": "#ECEFF4",
        },
    ),
    "catppuccin_mocha": (
        "Catppuccin Mocha — тёмная",
        {
            "window": "#1E1E2E",
            "canvas": "#1E1E2E",
            "surface": "#1E1E2E",
            "sidebar": "#181825",
            "sidebar_hover": "#232334",
            "sidebar_selection": "#313244",
            "subtle": "#262637",
            "hairline": "#313244",
            "field": "#292A3B",
            "field_hover": "#313244",
            "text": "#CDD6F4",
            "secondary": "#A6ADC8",
            "tertiary": "#6C7086",
            "header_text": "#7F849C",
            "accent": "#89B4FA",
            "accent_hover": "#A4C4FB",
            "accent_soft": "#2B3450",
            "selection": "#323D5A",
            "on_accent": "#1E1E2E",
            "green": "#A6E3A1",
            "green_soft": "#2A3B33",
            "amber": "#F9E2AF",
            "amber_soft": "#3B3628",
            "red": "#F38BA8",
            "red_soft": "#43293A",
            "violet": "#CBA6F7",
            "teal": "#94E2D5",
            "scrollbar": "#45475A",
            "scrollbar_hover": "#585B70",
            "tooltip": "#313244",
            "tooltip_text": "#CDD6F4",
        },
    ),
}
DEFAULT_THEME = "things"
P = Palette()
_current = DEFAULT_THEME


def set_theme(name: str) -> str:
    """Switch the palette to a theme (an unknown name: the default); returns its name.
    The look changes once apply() runs and the pages are built again."""
    global _current
    _current = name if name in THEMES else DEFAULT_THEME
    base, changes = Palette(), THEMES[_current][1]
    for f in fields(Palette):
        setattr(P, f.name, changes.get(f.name, getattr(base, f.name)))
    return _current


def current_theme() -> str:
    return _current


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
        # Table cells: only the property is set, the rest comes from the view's font.
        self.cell_italic = QFont()
        self.cell_italic.setItalic(True)
        self.cell_bold = QFont()
        self.cell_bold.setWeight(QFont.Weight.DemiBold)


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
        p.setPen(QColor(P.on_accent))
        f = QFont(fonts().text_family, 8)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Mode.Selected)  # keep full color when the item is selected
    return icon


def check_icon(done: bool, size: int = 16) -> QIcon:
    """A circle like Things' checkbox: hollow — still to do (a draft), filled in the
    accent with a white check — done (posted)."""
    pm = QPixmap(size * 2, size * 2)  # 2x for HiDPI
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(2, 2, size - 4, size - 4)
    if done:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P.accent))
        p.drawEllipse(box)
        pen = QPen(QColor(P.on_accent), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        s = size / 16
        p.drawPolyline(
            [QPointF(5.2 * s, 8.2 * s), QPointF(7.2 * s, 10.2 * s), QPointF(10.8 * s, 6.2 * s)]
        )
    else:
        p.setPen(QPen(QColor(P.tertiary), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(box)
    p.end()
    icon = QIcon(pm)
    icon.addPixmap(pm, QIcon.Mode.Selected)
    return icon


def _check_mark(color: str) -> str:
    """A check mark image in the color (a stylesheet takes images only from files)."""
    path = Path(tempfile.gettempdir()) / "modern-gl" / f"check-{color.lstrip('#')}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(32, 32, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 4.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(8, 16.5), QPointF(13.5, 22), QPointF(24, 10)])
        p.end()
        image.save(str(path))
    return path.as_posix()


def stylesheet() -> str:
    return f"""
* {{ outline: 0; }}
QMainWindow, QWidget#page {{ background: {P.canvas}; }}
QToolTip {{
    background: {P.tooltip}; color: {P.tooltip_text}; border: none; padding: 5px 8px;
    border-radius: 6px;
}}

/* Sidebar */
QWidget#sidebar {{ background: {P.sidebar}; border-right: 1px solid {P.hairline}; }}
QListWidget#nav {{ background: transparent; border: none; }}
QListWidget#nav::item {{
    color: {P.text}; padding: 6px 8px; margin: 1px 10px; border-radius: 7px;
}}
QListWidget#nav::item:hover {{ background: {P.sidebar_hover}; }}
QListWidget#nav::item:selected {{ background: {P.sidebar_selection}; color: {P.text}; }}
QListWidget#nav::item:disabled {{ color: {P.tertiary}; background: transparent; }}
QPushButton#company {{
    text-align: left; padding: 10px 12px; margin: 14px 10px 8px 10px; border: none;
    border-radius: 8px; color: {P.text}; background: transparent;
}}
QPushButton#company:hover {{ background: {P.sidebar_hover}; }}
QPushButton#company::menu-indicator {{ image: none; }}

/* Buttons */
QPushButton {{
    background: {P.surface}; color: {P.text}; border: 1px solid {P.hairline};
    border-radius: 7px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {P.subtle}; }}
QPushButton:disabled {{ color: {P.tertiary}; }}
QPushButton#primary {{
    background: {P.accent}; color: {P.on_accent}; border: 1px solid {P.accent}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {P.accent_hover}; }}
QPushButton#primary:disabled {{
    background: {P.accent_soft}; border-color: {P.accent_soft}; color: {P.surface};
}}
QPushButton#flat {{ background: transparent; border: none; color: {P.accent}; padding: 6px 8px; }}
QPushButton#flat:hover {{ background: {P.accent_soft}; }}
QPushButton#more {{
    background: transparent; border: none; color: {P.secondary}; padding: 2px 10px 6px 10px;
    font-size: 14pt; border-radius: 7px;
}}
QPushButton#more:hover {{ background: {P.field}; color: {P.text}; }}
QPushButton#danger {{ background: transparent; border: none; color: {P.red}; padding: 6px 8px; }}
QPushButton#danger:hover {{ background: {P.red_soft}; }}
QPushButton#dangerSolid {{
    background: {P.red}; color: {P.on_accent}; border: 1px solid {P.red}; font-weight: 600;
}}
QPushButton#dangerSolid:disabled {{
    background: {P.red_soft}; border: 1px solid {P.red_soft}; color: {P.surface};
}}
QPushButton#fab {{
    background: {P.accent}; color: {P.on_accent}; border: none; border-radius: 26px;
    font-size: 22pt; padding: 0 0 4px 0;
}}
QPushButton#fab:hover {{ background: {P.accent_hover}; }}
/* a choice of two or three: Mədaxil | Məxaric */
QPushButton#segment {{
    background: {P.field}; border: none; border-radius: 7px; color: {P.secondary};
    padding: 6px 16px;
}}
QPushButton#segment:hover {{ background: {P.field_hover}; color: {P.text}; }}
QPushButton#segment:checked {{ background: {P.accent_soft}; color: {P.accent}; font-weight: 600; }}

/* Inputs */
QLineEdit, QDateEdit, QComboBox {{
    background: {P.field}; border: 1px solid {P.sheet_border}; border-radius: 7px;
    padding: 5px 8px; color: {P.text}; selection-background-color: {P.accent};
}}
QLineEdit:hover, QDateEdit:hover, QComboBox:hover {{ background: {P.field_hover}; }}
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
    background: {P.surface}; border: 1px solid {P.sheet_border}; border-radius: 12px;
    gridline-color: transparent; padding: {P.sheet_padding};
    selection-background-color: {P.selection}; selection-color: {P.text};
}}
/* lists (journal, chart, directories…): no rule under each row, air and hover instead */
QTableView#list::item {{ border-bottom: 1px solid transparent; }}
QTableView::item {{ border-bottom: 1px solid {P.hairline}; padding: 0 8px; }}
QTableView::item:hover {{ background: {P.subtle}; }}
QTableView::item:selected {{ background: {P.selection}; color: {P.text}; }}
QTableView QLineEdit {{
    background: {P.surface}; border: 1px solid {P.accent}; border-radius: 4px; padding: 0 6px;
}}
QHeaderView {{ background: {P.surface}; border: none; }}
QHeaderView::section {{
    background: {P.surface}; color: {P.header_text}; border: none;
    border-bottom: 1px solid {P.hairline}; padding: 6px 11px;  /* = cell padding + text margin */
}}
QHeaderView::section:vertical {{
    color: {P.tertiary}; border: none; border-bottom: 1px solid {P.hairline}; padding: 0 6px;
}}
QTableCornerButton::section {{ background: {P.surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P.scrollbar}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {P.scrollbar_hover}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {P.scrollbar}; border-radius: 3px; min-width: 30px; }}
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
/* drawn here, not by the style: its box is "the background a bit darker" — lost on dark */
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {P.scrollbar_hover}; border-radius: 4px;
    background: {P.surface};
}}
QCheckBox::indicator:hover {{ border-color: {P.accent}; }}
QCheckBox::indicator:checked {{
    background: {P.accent}; border-color: {P.accent}; image: url({_check_mark(P.on_accent)});
}}
QCheckBox::indicator:disabled {{ background: {P.subtle}; border-color: {P.hairline}; }}
QCheckBox::indicator:checked:disabled {{ background: {P.accent_soft}; }}

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
QFrame#note {{ background: {P.accent_soft}; border: none; border-radius: 8px; }}
QFrame#card {{
    background: {P.surface}; border: 1px solid {P.hairline}; border-radius: 12px;
}}
QFrame#card QLabel {{ background: transparent; border: none; }}
QFrame#note QLabel {{ color: {P.text}; background: transparent; }}
QFrame#note QPushButton#flat:hover {{ background: {P.selection}; }}
/* the bank accounts beside their statement */
QListWidget#places {{ background: transparent; border: none; outline: none; }}
QListWidget#places::item {{ border-radius: 8px; color: {P.text}; }}
QListWidget#places::item:hover {{ background: {P.subtle}; }}
QListWidget#places::item:selected {{ background: {P.selection}; color: {P.text}; }}
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
    # dialogs, calendars and message boxes draw with these (dark themes)
    pal.setColor(QPalette.ColorRole.Button, QColor(P.surface))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(P.tooltip))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(P.tooltip_text))
    pal.setColor(QPalette.ColorRole.Light, QColor(P.subtle))
    pal.setColor(QPalette.ColorRole.Midlight, QColor(P.hairline))
    pal.setColor(QPalette.ColorRole.Mid, QColor(P.hairline))
    pal.setColor(QPalette.ColorRole.Dark, QColor(P.tertiary))
    pal.setColor(QPalette.ColorRole.Link, QColor(P.accent))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())
