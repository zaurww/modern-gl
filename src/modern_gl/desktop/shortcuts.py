"""One table of the program's keys (D165). A page binds a key by its id — `bind(self,
"post", self.post)` — and the table says which keys it is and how far it reaches (its
scope); the legends under the tables («Ins — строка · F9 — копия строки…») are made from
the same table, so a key and its description cannot drift apart. Two actions cannot share
keys in one scope (`tests/test_shortcuts.py`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from modern_gl.i18n import N_, tr


class Scope(Enum):
    """How far a bound key reaches, and so what it may not clash with."""

    WINDOW = "window"  # anywhere in the window
    PAGE = "page"  # the widget it is bound to and everything in it (a cell editor too)
    GRID = "grid"  # the table itself only: not while a cell is being edited
    TYPED = "typed"  # not a shortcut: the table handles it in keyPressEvent (shown in legends)


CONTEXT = {
    Scope.WINDOW: Qt.ShortcutContext.WindowShortcut,
    Scope.PAGE: Qt.ShortcutContext.WidgetWithChildrenShortcut,
    Scope.GRID: Qt.ShortcutContext.WidgetShortcut,
}


@dataclass(frozen=True)
class Key:
    id: str
    keys: tuple[str, ...]  # «Return» and «Enter» are both given: the keypad's is another key
    scope: Scope
    hint: str  # what it does, in Russian (tr() on display)


def _k(id: str, keys: str | tuple[str, ...], scope: Scope, hint: str) -> Key:
    return Key(id, (keys,) if isinstance(keys, str) else keys, scope, hint)


ENTER = ("Return", "Enter")
CTRL_ENTER = ("Ctrl+Return", "Ctrl+Enter")
CTRL_SHIFT_ENTER = ("Ctrl+Shift+Return", "Ctrl+Shift+Enter")

KEYS: dict[str, Key] = {
    k.id: k
    for k in (
        # ---- the window ----------------------------------------------------------------
        _k("new_document", "Ctrl+N", Scope.WINDOW, N_("новый документ")),
        _k("close_page", ("Ctrl+W", "Ctrl+F4"), Scope.WINDOW, N_("закрыть")),
        _k("palette", "Ctrl+K", Scope.WINDOW, N_("поиск и команды")),
        _k("quick_entry", "Ctrl+L", Scope.WINDOW, N_("быстрая строка")),
        _k("go_journal", "Ctrl+1", Scope.WINDOW, N_("Журнал")),
        _k("go_osv", "Ctrl+2", Scope.WINDOW, N_("ОСВ")),
        _k("go_chart", "Ctrl+3", Scope.WINDOW, N_("План счетов")),
        _k("go_directories", "Ctrl+4", Scope.WINDOW, N_("Справочники")),
        _k("go_templates", "Ctrl+5", Scope.WINDOW, N_("Шаблоны")),
        _k("go_inventory", "Ctrl+6", Scope.WINDOW, N_("Склад")),
        _k("go_currencies", "Ctrl+7", Scope.WINDOW, N_("Валюты")),
        _k("go_invoices", "Ctrl+8", Scope.WINDOW, "E-qaimələr"),
        _k("go_opening", "Ctrl+9", Scope.WINDOW, N_("Начальные остатки")),
        _k("go_purchases", "Ctrl+0", Scope.WINDOW, N_("Покупки")),
        _k("go_sales", "Ctrl+-", Scope.WINDOW, N_("Продажи")),
        _k("go_bank", "Ctrl+B", Scope.WINDOW, N_("Банк")),
        # ---- a page and everything in it ------------------------------------------------
        _k("save", "Ctrl+S", Scope.PAGE, N_("сохранить")),
        _k("post", CTRL_ENTER, Scope.PAGE, N_("провести")),
        _k(
            "post_and_new",
            ("Ctrl+Shift+Return", "Ctrl+Shift+Enter"),
            Scope.PAGE,
            N_("провести и новый"),
        ),
        _k(
            "insert", "Ins", Scope.PAGE, N_("строка")
        ),  # a line of a document; in a list — a new item
        _k("duplicate_row", "F9", Scope.PAGE, N_("копия строки")),
        _k("split_row", "F8", Scope.PAGE, N_("разделить строку")),
        _k("fee", "F6", Scope.PAGE, N_("комиссия")),
        _k("remove_line", "Ctrl+Del", Scope.PAGE, N_("убрать строку")),
        _k("edit", "F2", Scope.PAGE, N_("изменить")),
        _k("open", ENTER, Scope.PAGE, N_("открыть")),
        _k("refresh", "F5", Scope.PAGE, N_("обновить")),
        _k("find", "Ctrl+F", Scope.PAGE, N_("поиск")),
        _k("copy_report", "Ctrl+C", Scope.PAGE, N_("копировать для Excel")),
        _k("paste", "Ctrl+V", Scope.PAGE, N_("вставить")),
        _k("previous", "Alt+Left", Scope.PAGE, N_("предыдущая")),
        _k("next", "Alt+Right", Scope.PAGE, N_("следующая")),
        _k("up", ("Backspace", "Alt+Up"), Scope.PAGE, N_("на уровень выше")),
        # ---- the table only (not while a cell is edited: there the keys type) -----------
        _k("delete", "Del", Scope.GRID, N_("удалить строку")),
        _k("open_row", ENTER, Scope.GRID, N_("открыть")),
        _k("check_row", "Space", Scope.GRID, N_("проверено")),
        _k("copy_document", "F9", Scope.GRID, N_("копия документа")),
        _k("add_charge", "Ins", Scope.GRID, N_("новый расход")),
        _k("copy_rows", "Ctrl+C", Scope.GRID, N_("копировать")),
        _k("paste_rows", "Ctrl+V", Scope.GRID, N_("вставить из Excel")),
        # ---- typed into the table, not shortcuts ----------------------------------------
        _k("next_field", ("Return", "Tab"), Scope.TYPED, N_("дальше")),
        _k("previous_field", "Shift+Tab", Scope.TYPED, N_("назад")),
        _k("template", "#", Scope.TYPED, N_("шаблон")),
    )
}

# the sidebar's places with a key of their own: go_journal is Ctrl+1…
PLACES_BY_KEY = tuple(k.id[len("go_") :] for k in KEYS.values() if k.id.startswith("go_"))
SEPARATOR = "   ·   "


def bind(widget: QWidget, id: str, slot: Callable[[], object]) -> list[QShortcut]:
    """The key `id` on `widget`, reaching as far as its scope says."""
    key = KEYS[id]
    if key.scope is Scope.TYPED:
        raise ValueError(f"{id} is typed into the table, not bound")
    made = []
    for keys in key.keys:
        shortcut = QShortcut(QKeySequence(keys), widget)
        shortcut.setContext(CONTEXT[key.scope])
        shortcut.activated.connect(slot)
        made.append(shortcut)
    return made


def label(id: str) -> str:
    """The keys as shown to the user: «Ctrl+Enter», «Enter, Tab»."""
    shown = dict.fromkeys(k.replace("Return", "Enter") for k in KEYS[id].keys)
    return ", ".join(shown)


def legend(*ids: str) -> str:
    """«Enter, Tab — дальше   ·   Ins — строка…»: the keys of a page, under its table."""
    return SEPARATOR.join(f"{label(i)} — {tr(KEYS[i].hint)}" for i in ids)


def key_line(id: str) -> str:
    """«Ctrl+K  поиск и команды»: one key on a line of the sidebar's hint."""
    return f"{KEYS[id].keys[0]}  {tr(KEYS[id].hint)}"  # the first keys only: short
