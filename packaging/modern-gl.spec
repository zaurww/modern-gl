# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build of the desktop program (`uv run pyinstaller packaging/modern-gl.spec`):
one folder `dist/modern-gl` with the interpreter, PySide6 and the package's data — the
icons and fonts (`desktop/resources`), the migrations and the chart templates
(`infrastructure/*`), which the code reads next to its own files."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "src" / "modern_gl"

datas = [
    (str(PACKAGE / "desktop" / "resources"), "modern_gl/desktop/resources"),
    (str(PACKAGE / "infrastructure" / "migrations"), "modern_gl/infrastructure/migrations"),
    (str(PACKAGE / "infrastructure" / "templates"), "modern_gl/infrastructure/templates"),
]

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    # the translations (`i18n_az`) are found with pkgutil, the modules of the ledger are
    # imported lazily: nothing names them, so every submodule is collected
    hiddenimports=collect_submodules("modern_gl"),
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="modern-gl",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="modern-gl")
