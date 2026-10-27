"""What the program remembers for the user is in one place (desktop/preferences.py, D166):
QSettings is created there only, and each key reads back with its type and default."""

import ast
from pathlib import Path

from PySide6.QtCore import QSettings

from modern_gl.desktop.preferences import (
    BANK_AMOUNTS,
    PINNED_REPORTS,
    STOCK_COUNT_WAREHOUSE,
    Preferences,
    prefs,
)

SRC = Path(__file__).parent.parent / "src" / "modern_gl"
# the one module that makes QSettings; everything else asks it
MAKER = {"desktop/preferences.py"}


def made_in(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "QSettings"
    ]


def settings_made() -> list[str]:
    found = []
    for path in SRC.rglob("*.py"):
        where = path.relative_to(SRC).as_posix()
        if where not in MAKER:
            found += [f"{where}:{line}" for line in made_in(path)]
    return found


def test_settings_are_made_in_preferences_only():
    assert settings_made() == []


def test_defaults_when_nothing_is_remembered():
    p = prefs()
    assert p.grid() is True and p.zebra() is False
    assert p.idle_items_shown() is True
    assert p.chosen_id(STOCK_COUNT_WAREHOUSE) == -1
    assert p.report_ids(PINNED_REPORTS) is None
    assert p.last_account() is None
    assert p.view(BANK_AMOUNTS, "two") == "two"
    assert p.columns("osv") == ""


def test_what_is_set_reads_back_typed():
    prefs().set_grid(False)
    prefs().set_chosen_id(STOCK_COUNT_WAREHOUSE, 7)
    prefs().set_report_ids(PINNED_REPORTS, ["osv", "card"])
    prefs().set_last_account(42)
    p = prefs()  # a new one: the same store
    assert p.grid() is False
    assert p.chosen_id(STOCK_COUNT_WAREHOUSE) == 7
    assert p.report_ids(PINNED_REPORTS) == ["osv", "card"]
    assert p.last_account() == 42


def test_a_window_may_be_given_a_file_of_its_own(tmp_path):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    Preferences(store).set_user_name("Aysel")
    assert Preferences(store).user_name() == "Aysel"
    assert prefs().user_name() == ""
