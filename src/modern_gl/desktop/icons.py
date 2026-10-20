"""Line icons drawn with QPainter, like the glyphs of Things: one stroke weight, rounded
ends, color only where it means something. No image files, sharp at any scale.

Each icon is drawn in an 18 x 18 box (2x pixels for HiDPI).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

STROKE = 1.6


def _journal(p: QPainter) -> None:  # a list: three lines with bullets
    for y in (5.0, 9.0, 13.0):
        p.drawPoint(QPointF(3.5, y))
        p.drawLine(QPointF(6.5, y), QPointF(15, y))


def _osv(p: QPainter) -> None:  # scales: debit and credit in balance
    p.drawLine(QPointF(9, 3), QPointF(9, 15))
    p.drawLine(QPointF(5.5, 15), QPointF(12.5, 15))
    p.drawLine(QPointF(3, 5.5), QPointF(15, 5.5))
    for x in (4.5, 13.5):
        path = QPainterPath(QPointF(x - 2.5, 10))
        path.lineTo(x, 5.5)
        path.lineTo(x + 2.5, 10)
        path.arcTo(QRectF(x - 2.5, 8.5, 5, 3), 180, 180)
        p.drawPath(path)


def _opening(p: QPainter) -> None:  # a starting line with balances entering the ledger
    p.drawLine(QPointF(3, 4), QPointF(3, 14))
    p.drawLine(QPointF(6, 6), QPointF(15, 6))
    p.drawLine(QPointF(6, 12), QPointF(15, 12))
    p.drawLine(QPointF(11.5, 3.5), QPointF(15, 6))
    p.drawLine(QPointF(11.5, 8.5), QPointF(15, 6))


def _chart(p: QPainter) -> None:  # a tree: account and its subaccounts
    p.drawRoundedRect(QRectF(2.5, 2.5, 6, 4), 1.2, 1.2)
    p.drawLine(QPointF(5.5, 6.5), QPointF(5.5, 13.5))
    for y in (9.5, 13.5):
        p.drawLine(QPointF(5.5, y), QPointF(9, y))
        p.drawRoundedRect(QRectF(9.5, y - 2, 6, 4), 1.2, 1.2)


def _inventory(p: QPainter) -> None:  # a box
    path = QPainterPath(QPointF(9, 2.5))
    path.lineTo(15.5, 5.5)
    path.lineTo(15.5, 12.5)
    path.lineTo(9, 15.5)
    path.lineTo(2.5, 12.5)
    path.lineTo(2.5, 5.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(2.5, 5.5), QPointF(9, 8.5))
    p.drawLine(QPointF(15.5, 5.5), QPointF(9, 8.5))
    p.drawLine(QPointF(9, 8.5), QPointF(9, 15.5))


def _directories(p: QPainter) -> None:  # a book with a bookmark
    p.drawRoundedRect(QRectF(3.5, 2.5, 11, 13), 1.8, 1.8)
    p.drawLine(QPointF(6.5, 2.5), QPointF(6.5, 15.5))
    p.drawLine(QPointF(9, 6.5), QPointF(12, 6.5))
    p.drawLine(QPointF(9, 9.5), QPointF(12, 9.5))


def _templates(p: QPainter) -> None:  # two stacked sheets: a reusable entry
    p.drawRoundedRect(QRectF(5.5, 2.5, 10, 10), 1.8, 1.8)
    path = QPainterPath(QPointF(3.5, 5.5))
    path.lineTo(2.5, 5.5)
    path.lineTo(2.5, 15.5)
    path.lineTo(12.5, 15.5)
    path.lineTo(12.5, 14.5)
    p.drawPath(path)


def _currencies(p: QPainter) -> None:  # two coins
    p.drawEllipse(QRectF(2.5, 2.5, 9, 9))
    p.drawArc(QRectF(6.5, 6.5, 9, 9), -60 * 16, 210 * 16)


def _invoices(p: QPainter) -> None:  # a receipt with a torn edge
    path = QPainterPath(QPointF(4, 15.5))
    path.lineTo(4, 2.5)
    path.lineTo(14, 2.5)
    path.lineTo(14, 15.5)
    for x in (12.33, 10.67, 9, 7.33, 5.67, 4):
        path.lineTo(x, 14.3 if round((14 - x) / 1.67) % 2 else 15.5)
    p.drawPath(path)
    p.drawLine(QPointF(6.5, 6), QPointF(11.5, 6))
    p.drawLine(QPointF(6.5, 9), QPointF(11.5, 9))


def _trade(p: QPainter) -> None:  # two arrows: bought in, sold out
    p.drawLine(QPointF(3, 6), QPointF(15, 6))
    p.drawLine(QPointF(12, 3), QPointF(15, 6))
    p.drawLine(QPointF(12, 9), QPointF(15, 6))
    p.drawLine(QPointF(3, 12), QPointF(15, 12))
    p.drawLine(QPointF(6, 9), QPointF(3, 12))
    p.drawLine(QPointF(6, 15), QPointF(3, 12))


def _bank(p: QPainter) -> None:  # a bank: a pediment on columns
    path = QPainterPath(QPointF(2.5, 6.5))
    path.lineTo(9, 2.5)
    path.lineTo(15.5, 6.5)
    path.closeSubpath()
    p.drawPath(path)
    for x in (4.5, 9.0, 13.5):
        p.drawLine(QPointF(x, 8.5), QPointF(x, 12.5))
    p.drawLine(QPointF(2.5, 15), QPointF(15.5, 15))


def _document(p: QPainter) -> None:  # a sheet with a folded corner
    path = QPainterPath(QPointF(4, 2.5))
    path.lineTo(10.5, 2.5)
    path.lineTo(14, 6)
    path.lineTo(14, 15.5)
    path.lineTo(4, 15.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(10.5, 2.5), QPointF(10.5, 6))
    p.drawLine(QPointF(10.5, 6), QPointF(14, 6))
    p.drawLine(QPointF(6.5, 9.5), QPointF(11.5, 9.5))
    p.drawLine(QPointF(6.5, 12.5), QPointF(11.5, 12.5))


def _new(p: QPainter) -> None:  # a plus
    p.drawLine(QPointF(9, 3.5), QPointF(9, 14.5))
    p.drawLine(QPointF(3.5, 9), QPointF(14.5, 9))


def _report(p: QPainter) -> None:  # bars
    for x, top in ((4, 9.5), (9, 4.5), (14, 7.5)):
        p.drawLine(QPointF(x, top), QPointF(x, 15))


def _import(p: QPainter) -> None:  # an arrow into a tray
    p.drawLine(QPointF(9, 2.5), QPointF(9, 10.5))
    p.drawLine(QPointF(5.5, 7.5), QPointF(9, 11))
    p.drawLine(QPointF(12.5, 7.5), QPointF(9, 11))
    path = QPainterPath(QPointF(2.5, 11))
    path.lineTo(2.5, 15.5)
    path.lineTo(15.5, 15.5)
    path.lineTo(15.5, 11)
    p.drawPath(path)


GLYPHS: dict[str, Callable[[QPainter], None]] = {
    "journal": _journal,
    "osv": _osv,
    "opening": _opening,
    "chart": _chart,
    "inventory": _inventory,
    "trade": _trade,
    "bank": _bank,
    "directories": _directories,
    "templates": _templates,
    "currencies": _currencies,
    "invoices": _invoices,
    "document": _document,
    "new": _new,
    "report": _report,
    "import": _import,
}

_CACHE: dict[tuple[str, str, int], QIcon] = {}


def icon(name: str, color: str, size: int = 18) -> QIcon:
    """A line icon in one color; selected items keep it as it is."""
    key = (name, color, size)
    if key not in _CACHE:
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 18, size / 18)
        pen = QPen(QColor(color), STROKE)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        GLYPHS[name](p)
        p.end()
        result = QIcon(pm)
        result.addPixmap(pm, QIcon.Mode.Selected)
        _CACHE[key] = result
    return _CACHE[key]
