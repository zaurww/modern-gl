"""Fonts of the program: one text family, sizes for titles, captions and cells."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase


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
