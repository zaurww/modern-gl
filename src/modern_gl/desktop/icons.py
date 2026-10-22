"""Line icons from one set, Lucide (lucide.dev, ISC; `resources/icons`): one stroke weight,
rounded ends, grey where they only name a place, the accent where they mean something (D86).

An icon is drawn from its SVG in the asked color, 2x pixels for HiDPI.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

FOLDER = Path(__file__).parent / "resources" / "icons"
STROKE = "1.75"  # Lucide draws 2 on 24: a bit lighter at 18, like the text beside it

# the program's name of an icon -> the Lucide file
GLYPHS: dict[str, str] = {
    "journal": "list",
    "osv": "scale",
    "opening": "flag",
    "chart": "list-tree",
    "inventory": "package",
    "purchases": "log-in",
    "sales": "log-out",
    "bank": "landmark",
    "directories": "book",
    "folder": "folder",
    "templates": "copy",
    "currencies": "coins",
    "invoices": "receipt",
    "document": "file-text",
    "new": "plus",
    "report": "chart-column",
    "import": "import",
    "today": "sun",
    "home": "sun",
    "search": "search",
    "next": "chevron-right",
    "more": "ellipsis",
    "check": "check",
    "account": "hash",
    "counterparty": "building-2",
    "command": "zap",
    "palette": "command",
    "attention": "circle-alert",
    "money": "wallet",
    "down": "chevron-down",
    "back": "arrow-left",
    "forward": "arrow-right",
    "lock": "lock",
    "books": "git-compare",
    "statements": "chart-pie",
}

_CACHE: dict[tuple[str, str, int, str], QIcon] = {}


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    svg = (FOLDER / f"{GLYPHS[name]}.svg").read_text(encoding="utf-8")
    svg = svg.replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{STROKE}"')
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def icon(name: str, color: str, size: int = 18, selected: str = "") -> QIcon:
    """A line icon in one color; a selected item shows it in `selected` (or the same)."""
    key = (name, color, size, selected)
    if key not in _CACHE:
        pm = _pixmap(name, color, size)
        result = QIcon(pm)
        result.addPixmap(_pixmap(name, selected, size) if selected else pm, QIcon.Mode.Selected)
        _CACHE[key] = result
    return _CACHE[key]


def status_mark(posted: bool, accent: str, amber: str, size: int = 16) -> QIcon:
    """A document's status: a posted one — Lucide's check in the accent; a draft — a small
    amber dot, «still to do» (a mark, not an icon). No circle outline: that reads as a
    checkbox to click (D73)."""
    if posted:
        return icon("check", accent, size, selected=accent)
    pm = QPixmap(size * 2, size * 2)  # 2x for HiDPI
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 16
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(amber))
    p.drawEllipse(QPointF(8 * s, 8 * s), 3.5 * s, 3.5 * s)
    p.end()
    dot = QIcon(pm)
    dot.addPixmap(pm, QIcon.Mode.Selected)  # keep the color when the row is selected
    return dot
