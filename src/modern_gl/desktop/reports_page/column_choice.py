"""Which columns a report shows, in what order and how wide: a right click on the captions
(or «⋯ → Колонки») ticks a column on or off; a rarely needed one (VÖEN) starts hidden; a
caption dragged with the mouse moves its column (a Dt/Kt pair moves whole), its edge
dragged — the width. All of it is remembered for the kind of report between sessions;
the first column (the names) always stays, and first. «Колонки по умолчанию» forgets it."""

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


def width_id(col: Column) -> str:
    """Each column of a pair has a width of its own («Обороты|Дт»)."""
    return f"{column_id(col)}|{col.title}" if col.group else column_id(col)


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

    def arrange(self, columns: list[Column]) -> list[Column]:
        """The columns in the order the user moved them to; one the order does not know
        (new in the report) keeps its place among the rest, a pair stays together."""
        order = {cid: i for i, cid in enumerate(prefs().column_order(self.kind))}
        if not order or not columns:
            return columns
        rest = columns[1:]
        known = sorted(
            (order[column_id(c)], i) for i, c in enumerate(rest) if column_id(c) in order
        )
        slots = sorted(i for _, i in known)  # the places of the known ones, filled in order
        placed = list(rest)
        for slot, (_, i) in zip(slots, known, strict=True):
            placed[slot] = rest[i]
        return columns[:1] + _pairs_together(placed)

    def widths(self) -> dict[str, int]:
        return prefs().column_widths(self.kind)

    def choose(self, cid: str, on: bool) -> None:
        self._save({**self.choice, cid: on})

    def move(self, ids: list[str]) -> None:
        """The columns now stand so (column ids, the first column left out)."""
        prefs().set_column_order(self.kind, ids)

    def set_width(self, wid: str, px: int) -> None:
        prefs().set_column_widths(self.kind, {**self.widths(), wid: px})

    def remembered(self) -> bool:
        return bool(self.choice or prefs().column_order(self.kind) or self.widths())

    def reset(self) -> None:
        prefs().set_column_order(self.kind, [])
        prefs().set_column_widths(self.kind, {})
        self._save({})

    def _save(self, choice: dict[str, bool]) -> None:
        lines = [("+" if on else "-") + cid for cid, on in choice.items()]
        prefs().set_columns(self.kind, "\n".join(lines))
        self.on_change()

    def popup(self, columns: list[Column], parent: QWidget, at: QPoint) -> None:
        """A menu of the columns, each with a tick when it is shown."""
        menu = QMenu(parent)
        seen: set[str] = set()
        for col in self.arrange(columns)[1:]:
            cid = column_id(col)
            if cid in seen:
                continue
            seen.add(cid)
            on = self.shown(col)
            action = menu.addAction(("✓  " if on else "     ") + (col.group or col.title))
            action.triggered.connect(lambda _=False, cid=cid, on=on: self.choose(cid, not on))
        if self.remembered():
            menu.addSeparator()
            menu.addAction(tr("Колонки по умолчанию")).triggered.connect(self.reset)
        if seen:
            menu.exec(at)


def _pairs_together(columns: list[Column]) -> list[Column]:
    """The columns of one id next to each other, where the first of them stands."""
    groups: dict[str, list[Column]] = {}
    for col in columns:
        groups.setdefault(column_id(col), []).append(col)
    return [col for members in groups.values() for col in members]
