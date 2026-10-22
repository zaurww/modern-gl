"""Fonts of the program: one text family, sizes for titles, captions and cells.

The family is Inter (rsms.me/inter, OFL; `resources/fonts`), carried with the program so
it looks the same on every computer. In tables and totals its figures are of one width
(`tnum`), so sums stand in a column (D86); not in text, where `tnum` widens the hyphen too.
Without the files — the system's Segoe UI.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FOLDER = Path(__file__).parent.parent / "resources" / "fonts"
TABULAR = QFont.Tag("tnum")


def _load_bundled() -> None:
    for path in sorted(FOLDER.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def _family(*candidates: str) -> str:
    available = set(QFontDatabase.families())
    return next((f for f in candidates if f in available), "Sans Serif")


def _font(
    family: str | None = None,
    size: int = 0,
    weight: QFont.Weight | None = None,
    tabular: bool = False,
) -> QFont:
    """No family: only the properties set (table cells); tabular: figures of one width."""
    font = QFont(family, size) if family else QFont()
    if weight is not None:
        font.setWeight(weight)
    if tabular:
        font.setFeature(TABULAR, 1)
    return font


class Fonts:
    """Created after QApplication exists."""

    def __init__(self) -> None:
        _load_bundled()
        text = _family("Inter", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue")
        display = text if text == "Inter" else _family("Segoe UI Variable Display", text)
        bold, semi = QFont.Weight.Bold, QFont.Weight.DemiBold
        self.text_family = text
        self.body = _font(text, 10)
        self.table = _font(text, 10, tabular=True)  # every table and list (theme.apply)
        self.small = _font(text, 9)
        self.caption = _font(text, 8, semi)
        self.caption.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        self.title = _font(display, 21, bold)
        self.title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
        self.heading = _font(display, 13, semi)
        self.total = _font(display, 15, semi, tabular=True)
        self.bold = _font(text, 10, semi)
        # Table cells: only the property is set, the rest comes from the view's font.
        self.cell_italic = _font(tabular=True)
        self.cell_italic.setItalic(True)
        self.cell_bold = _font(weight=semi, tabular=True)


FONTS: Fonts | None = None


def fonts() -> Fonts:
    global FONTS
    if FONTS is None:
        FONTS = Fonts()
    return FONTS
