"""The program's settings as the desktop stores them (QSettings «ModernGL / Modern GL»),
read without Qt: a tool beside the program (the assistant server, D83) finds the same
company files. On Windows they are in the registry; elsewhere nothing is known."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

KEY = r"Software\ModernGL\Modern GL"


@dataclass(frozen=True)
class AppSettings:
    """What the program remembers between runs (the Windows registry; empty elsewhere)."""

    data_dir: Path | None = None  # None: the default folder
    company_files: list[Path] = field(default_factory=list[Path])  # kept outside the folder
    language: str = ""


def default_folder() -> Path:
    """Documents\\Modern GL — what Qt gives the desktop when Documents is not moved."""
    return Path.home() / "Documents" / "Modern GL"


def read_settings() -> AppSettings:
    """The remembered settings; defaults when there are none or off Windows. Never raises."""
    if sys.platform != "win32":
        return AppSettings()
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY)
    except OSError:
        return AppSettings()
    with key:
        data_dir = _value(winreg, key, "data_dir")
        files = _value(winreg, key, "company_files")
        language = _value(winreg, key, "language")
    if isinstance(files, str):  # a single file may be stored as a plain string
        files = [files]
    return AppSettings(
        Path(data_dir) if isinstance(data_dir, str) and data_dir else None,
        [Path(f) for f in files if f] if isinstance(files, list) else [],
        language if isinstance(language, str) else "",
    )


def _value(winreg: ModuleType, key: object, name: str) -> object:
    """A value of the program's registry key; None when it is not there."""
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None
