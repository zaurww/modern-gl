"""Azerbaijani translations. Keys are the Russian source strings used in code.

A feature keeps its translations in a file of its own here (D131): parallel branches add
files, not lines at the end of one, and merge without a conflict. Every module of the
package with an `AZ` dict is read, in the order of the names; a key lives in one file
only (`tests/test_i18n.py`)."""

from __future__ import annotations

import importlib
import pkgutil

PARTS: dict[str, dict[str, str]] = {
    info.name: importlib.import_module(f"{__name__}.{info.name}").AZ
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name)
}
AZ: dict[str, str] = {key: text for part in PARTS.values() for key, text in part.items()}
