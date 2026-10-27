"""The table of keys (desktop/shortcuts.py, D-new2): no two actions share keys in one
scope, every description is translated, and the legends are made from it."""

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QWidget

from modern_gl.desktop.shortcuts import KEYS, bind, label, legend
from modern_gl.i18n import set_language
from modern_gl.i18n_az import AZ
from tests.helpers.texts import CYRILLIC


def test_no_two_actions_share_keys_in_one_scope():
    taken = Counter((key.scope, keys) for key in KEYS.values() for keys in key.keys)
    twice = {scope_keys: n for scope_keys, n in taken.items() if n > 1}
    assert not twice, twice


def test_every_description_is_translated():
    """A Russian description has its Azerbaijani; «E-qaimələr» is the same in both."""
    missing = [key.id for key in KEYS.values() if key.hint not in AZ and CYRILLIC & set(key.hint)]
    assert not missing, missing


def test_the_id_is_the_name():
    assert all(id == key.id for id, key in KEYS.items())


def test_bind_makes_a_shortcut_of_the_scope(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    hits = []
    made = bind(widget, "post", lambda: hits.append(1))
    assert [s.key().toString() for s in made] == ["Ctrl+Return", "Ctrl+Enter"]
    assert all(s.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut for s in made)
    assert widget.findChildren(QShortcut) == made
    grid = bind(widget, "delete", lambda: None)
    assert grid[0].context() == Qt.ShortcutContext.WidgetShortcut


def test_legend_is_made_from_the_table():
    set_language("ru")
    assert label("post") == "Ctrl+Enter"
    assert label("next_field") == "Enter, Tab"
    assert legend("next_field", "insert", "post") == (
        "Enter, Tab — дальше   ·   Ins — строка   ·   Ctrl+Enter — провести"
    )
    set_language("az")
    assert legend("post") == "Ctrl+Enter — keçir"
    set_language("ru")
