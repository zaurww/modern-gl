"""What the program remembers for the user between runs (D166): one object over QSettings
with a typed method for each key, instead of `QSettings().value("bank/amounts", …)` in
fourteen files. A key is named once, here; its type and default are here too. Nothing of a
company is kept here — that lives in its file.

`prefs()` gives a fresh object each time: QSettings is cheap, and tests point it at a
folder of their own (`tests/conftest.py`). Only this module creates QSettings
(`tests/test_preferences.py`)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

# ---- the program ---------------------------------------------------------------------
COMPANY_FILE = "company_file"  # the company opened last
COMPANY_FILES = "company_files"  # company files outside the data folder
DATA_DIR = "data_dir"  # the folder of company files (--data)
USER_NAME = "user_name"  # who works (D82)
LANGUAGE = "language"
THEME = "theme"
MIRROR_SETTING = "backup_mirror"  # the second folder for backups (D97)
# ---- the look of tables --------------------------------------------------------------
ZEBRA = "reports/zebra"  # «Оформление → Полосы в таблицах», off by default (D103)
GRID = "reports/grid"  # «Оформление → Сетка в отчётах», on by default (D127)
# ---- reports -------------------------------------------------------------------------
PINNED_REPORTS = "reports/pinned"  # D114
RECENT_REPORTS = "reports/recent"
LAST_ACCOUNT = "reports/last_account"  # the account asked last for a card
COLUMNS = "reports/columns/{kind}"  # «Колонки…» of a kind of report
COLUMN_ORDER = "reports/column_order/{kind}"  # columns moved with the mouse
COLUMN_WIDTHS = "reports/column_widths/{kind}"  # columns widened or narrowed with the mouse
STATEMENTS_VIEW = "reports/statements_view"  # D99
STATEMENTS_DETAIL = "reports/statements_detail"
STATEMENTS_COLUMNS = "reports/statements_columns"
STATEMENTS_PERCENT = "reports/statements_percent"  # a share of the revenue (D188)
SUBCONTO_LEVELS = "reports/subconto_levels"
SUBCONTO_ANALYSIS_KIND = "reports/subconto_analysis_kind"  # the directory asked last
STOCK_STATEMENT_VIEW = "reports/stock_statement_view"
GROSS_PROFIT_VIEW = "reports/gross_profit_view"
# ---- modules -------------------------------------------------------------------------
BANK_AMOUNTS = "bank/amounts"  # one column of amounts or two
INVENTORY_IDLE = "inventory/idle_items"  # items with nothing in stock listed too (D106)
STOCK_COUNT_WAREHOUSE = "stock_count/warehouse"  # the warehouse counted last


class Preferences:
    def __init__(self, store: QSettings | None = None) -> None:
        self.store = store if store is not None else QSettings()

    # ---- typed reading and writing -----------------------------------------------------

    def text(self, key: str, default: str = "") -> str:
        value = self.store.value(key, default)
        return default if value is None else str(value)

    def flag(self, key: str, default: bool) -> bool:
        return bool(self.store.value(key, default, type=bool))

    def number(self, key: str, default: int) -> int:
        value = self.store.value(key, default, type=int)
        return value if isinstance(value, int) else default

    def optional_number(self, key: str) -> int | None:
        value = self.store.value(key)
        return None if value is None or value == "" else int(str(value))

    def texts(self, key: str) -> list[str]:
        value = self.store.value(key, [], type=list)
        return [str(v) for v in value] if isinstance(value, list) else []

    def has(self, key: str) -> bool:
        return self.store.value(key) is not None

    def set(self, key: str, value: Any) -> None:
        self.store.setValue(key, value)

    # ---- the program -------------------------------------------------------------------

    def company_file(self) -> str:
        return self.text(COMPANY_FILE)

    def set_company_file(self, path: str) -> None:
        self.set(COMPANY_FILE, path)

    def set_company_files(self, paths: list[str]) -> None:
        self.set(COMPANY_FILES, paths)

    def user_name(self) -> str:
        return self.text(USER_NAME)

    def set_user_name(self, name: str) -> None:
        self.set(USER_NAME, name)

    def set_language(self, code: str) -> None:
        self.set(LANGUAGE, code)

    def set_theme(self, name: str) -> None:
        self.set(THEME, name)

    def set_backup_mirror(self, folder: str) -> None:
        self.set(MIRROR_SETTING, folder)

    # ---- the look of tables ------------------------------------------------------------

    def zebra(self) -> bool:
        return self.flag(ZEBRA, False)

    def set_zebra(self, on: bool) -> None:
        self.set(ZEBRA, on)

    def grid(self) -> bool:
        return self.flag(GRID, True)

    def set_grid(self, on: bool) -> None:
        self.set(GRID, on)

    # ---- reports -----------------------------------------------------------------------

    def report_ids(self, key: str) -> list[str] | None:
        """Pinned or recent reports, in their order; None — never chosen."""
        value = self.store.value(key)
        return None if value is None else [i for i in str(value).split(",") if i]

    def set_report_ids(self, key: str, ids: list[str]) -> None:
        self.set(key, ",".join(ids))

    def last_account(self) -> int | None:
        return self.optional_number(LAST_ACCOUNT)

    def set_last_account(self, account_id: int | None) -> None:
        self.set(LAST_ACCOUNT, account_id)

    def columns(self, kind: str) -> str:
        """«+VÖEN» shown, «-Договор» hidden, one a line: what the user chose."""
        return self.text(COLUMNS.format(kind=kind))

    def set_columns(self, kind: str, text: str) -> None:
        self.set(COLUMNS.format(kind=kind), text)

    def column_order(self, kind: str) -> list[str]:
        """The columns of a kind of report in the order the user moved them to; [] — as made."""
        return [line for line in self.text(COLUMN_ORDER.format(kind=kind)).splitlines() if line]

    def set_column_order(self, kind: str, ids: list[str]) -> None:
        self.set(COLUMN_ORDER.format(kind=kind), "\n".join(ids))

    def column_widths(self, kind: str) -> dict[str, int]:
        """The widths (px) the user gave columns with the mouse: «Дебет=120», one a line."""
        found: dict[str, int] = {}
        for line in self.text(COLUMN_WIDTHS.format(kind=kind)).splitlines():
            cid, _, px = line.rpartition("=")
            if cid and px.isdigit():
                found[cid] = int(px)
        return found

    def set_column_widths(self, kind: str, widths: dict[str, int]) -> None:
        lines = [f"{cid}={px}" for cid, px in widths.items()]
        self.set(COLUMN_WIDTHS.format(kind=kind), "\n".join(lines))

    def view(self, key: str, default: str) -> str:
        """The view of a page chosen last (statements, stock reports, bank amounts…)."""
        return self.text(key, default)

    def set_view(self, key: str, value: str) -> None:
        self.set(key, value)

    def chosen_id(self, key: str) -> int:
        """A directory, a warehouse, a level chosen last; -1 — none."""
        return self.number(key, -1)

    def set_chosen_id(self, key: str, value: int | None) -> None:
        self.set(key, value)

    # ---- modules -----------------------------------------------------------------------

    def idle_items_shown(self) -> bool:
        return self.flag(INVENTORY_IDLE, True)

    def set_idle_items_shown(self, on: bool) -> None:
        self.set(INVENTORY_IDLE, on)


def prefs() -> Preferences:
    """The user's preferences (a new QSettings over the same store)."""
    return Preferences()
