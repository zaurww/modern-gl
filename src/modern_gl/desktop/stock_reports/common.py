"""What the warehouse's reports share: a quantity column, the choice of a view."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from modern_gl.application.inventory import format_quantity
from modern_gl.desktop.preferences import prefs
from modern_gl.desktop.reports_page.view import Column
from modern_gl.desktop.widgets import segments


def quantity_text(quantity: int, precision: int) -> str:
    """A quantity as typed («12», «1.5»); zero — an empty cell (DESIGN.md 3)."""
    return format_quantity(quantity, precision) if quantity else ""


def quantity_column(title: str, get: Callable, group: str = "", **kwargs) -> Column:
    """A quantity of a row that has a unit (`has_quantity`): right-aligned like money."""
    return Column(
        title,
        lambda r: quantity_text(get(r), r.precision) if r.unit_code else "",
        right=True,
        group=group,
        **kwargs,
    )


def view_switch(
    setting: str, captions: list[tuple[str, str]], on_change: Callable[[], None]
) -> tuple[QWidget, Callable[[], str]]:
    """Segments «По товарам · По складам»: the one chosen last is remembered (D106)."""
    box, buttons = segments(captions, lambda: None)
    chosen = prefs().view(setting, captions[0][0])
    buttons.get(chosen, buttons[captions[0][0]]).setChecked(True)

    def current() -> str:
        return next(key for key, b in buttons.items() if b.isChecked())

    def changed(on: bool) -> None:
        if on:
            prefs().set_view(setting, current())
            on_change()

    for b in buttons.values():
        b.toggled.connect(changed)
    return box, current
