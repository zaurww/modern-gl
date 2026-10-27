"""Which columns a report shows: a right click on the captions (or «⋯ → Колонки») ticks
a column on or off; a rarely needed one (VÖEN) starts hidden. The choice is remembered
for the kind of report between sessions; the first column (the names) always stays."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QWidget

from modern_gl.desktop.preferences import prefs
from modern_gl.desktop.reports_page.table import Column
from modern_gl.i18n import tr


def column_id(col: Column) -> str:
    """A pair under one caption («Обороты»: Dt and Kt) is one choice."""
    return col.key or col.group or col.title


class ColumnChoice:
    def __init__(self, kind: str, on_change: Callable[[], None]) -> None:
        self.kind = kind
        self.on_change = on_change

    @property
    def choice(self) -> dict[str, bool]:
        """Read each time: two pages of one kind open show the same."""
        text = prefs().columns(self.kind)
        # "+VÖEN" shown, "-Договор" hidden: only what the user chose
        return {line[1:]: line[0] == "+" for line in text.splitlines() if line[:1] in ("+", "-")}

    def shown(self, col: Column) -> bool:
        return self.choice.get(column_id(col), not col.optional)

    def choose(self, cid: str, on: bool) -> None:
        self._save({**self.choice, cid: on})

    def reset(self) -> None:
        self._save({})

    def _save(self, choice: dict[str, bool]) -> None:
        lines = [("+" if on else "-") + cid for cid, on in choice.items()]
        prefs().set_columns(self.kind, "\n".join(lines))
        self.on_change()

    def popup(self, columns: list[Column], parent: QWidget, at: QPoint) -> None:
        """A menu of the columns, each with a tick when it is shown."""
        menu = QMenu(parent)
        seen: set[str] = set()
        for col in columns[1:]:
            cid = column_id(col)
            if cid in seen:
                continue
            seen.add(cid)
            on = self.shown(col)
            action = menu.addAction(("✓  " if on else "     ") + (col.group or col.title))
            action.triggered.connect(lambda _=False, cid=cid, on=on: self.choose(cid, not on))
        if self.choice:
            menu.addSeparator()
            menu.addAction(tr("Колонки по умолчанию")).triggered.connect(self.reset)
        if seen:
            menu.exec(at)
