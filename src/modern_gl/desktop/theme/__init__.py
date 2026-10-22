"""Visual language: calm, light, airy (inspired by Things), dense where it matters.

All colors and fonts live here as tokens; widgets never hardcode them.

Themes (THEMES) change some colors of the one palette; the user picks one in the
company menu. A new theme is one more entry there.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from modern_gl.desktop.theme.css import stylesheet
from modern_gl.desktop.theme.fonts import Fonts, fonts
from modern_gl.desktop.theme.icons import check_icon, dot_icon
from modern_gl.desktop.theme.palette import (
    DEFAULT_THEME,
    THEMES,
    P,
    Palette,
    current_theme,
    set_theme,
)

__all__ = [
    "DEFAULT_THEME",
    "THEMES",
    "Fonts",
    "P",
    "Palette",
    "apply",
    "check_icon",
    "current_theme",
    "dot_icon",
    "fonts",
    "set_theme",
    "stylesheet",
]


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    f = fonts()
    app.setFont(f.body)
    # the stub asks for bytes, PySide takes only a str
    app.setFont(f.table, "QAbstractItemView")  # pyright: ignore[reportArgumentType]
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
