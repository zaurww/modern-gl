"""The program's icon:  uv run python scripts/app_icon.py

Draws it from the theme — a rounded square of the accent blue with the white Lucide
«scale» glyph (the ОСВ icon) — and writes `src/modern_gl/desktop/resources/app.png`
(the window icon, 256 px) and `packaging/modern-gl.ico` (the exe and the installer:
16–256 px, PNG-compressed entries). Run again after a change of the accent or the glyph;
both files are committed.
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from modern_gl.desktop import theme
from modern_gl.desktop.icons import FOLDER

ROOT = Path(__file__).parent.parent
PNG = ROOT / "src" / "modern_gl" / "desktop" / "resources" / "app.png"
ICO = ROOT / "packaging" / "modern-gl.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
GLYPH = "scale"


def glyph_svg(color: str) -> bytes:
    svg = (FOLDER / f"{GLYPH}.svg").read_text(encoding="utf-8")
    return svg.replace("currentColor", color).encode()


def draw(size: int, accent: str, on_accent: str) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    p.fillPath(path, QColor(accent))
    inset = size * 0.2
    QSvgRenderer(QByteArray(glyph_svg(on_accent))).render(
        p, QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    )
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "icon.png"
        image.save(str(path))
        return path.read_bytes()


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    """ICONDIR + an entry per size, then the PNG blobs (Vista+ reads PNG entries)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        side = 0 if size == 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        blobs += blob
    return header + entries + blobs


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None
    theme.use_theme(theme.DEFAULT_THEME)
    accent, on_accent = theme.P.accent, theme.P.on_accent
    images = [(size, png_bytes(draw(size, accent, on_accent))) for size in SIZES]
    PNG.write_bytes(dict(images)[256])
    ICO.write_bytes(ico_bytes(images))
    print(f"{PNG.relative_to(ROOT)}, {ICO.relative_to(ROOT)} ({accent})")


if __name__ == "__main__":
    main()
