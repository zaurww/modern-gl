"""Icons drawn in code: sidebar squares, Things-like status circles, check marks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap

from modern_gl.desktop.theme.fonts import fonts
from modern_gl.desktop.theme.palette import P


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
