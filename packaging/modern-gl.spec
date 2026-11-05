# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build of the desktop program (`uv run pyinstaller packaging/modern-gl.spec`):
one folder `dist/modern-gl` with the interpreter, PySide6 and the package's data — the
icons and fonts (`desktop/resources`), the migrations and the chart templates
(`infrastructure/*`), which the code reads next to its own files."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "src" / "modern_gl"

datas = [
    (str(PACKAGE / "desktop" / "resources"), "modern_gl/desktop/resources"),
    (str(PACKAGE / "infrastructure" / "migrations"), "modern_gl/infrastructure/migrations"),
    (str(PACKAGE / "infrastructure" / "templates"), "modern_gl/infrastructure/templates"),
]
# the version the program shows comes from the package metadata (modern_gl.__version__)
datas += copy_metadata("modern-gl")

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    # the translations (`i18n_az`) are found with pkgutil, the modules of the ledger are
    # imported lazily: nothing names them, so every submodule is collected
    hiddenimports=collect_submodules("modern_gl"),
    # nothing of PySide6 is excluded: the portal window (portal_login) is the browser
    # QtWebEngine, imported lazily — an exclusion is only found by a user (0.1.1)
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
    icon=str(ROOT / "packaging" / "modern-gl.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="modern-gl")
