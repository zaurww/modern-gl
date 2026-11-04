"""The quantity of a counted account in a report (D-new): 01, 12… — how many chairs at
the start, came, went, are left; a cell with nothing is empty, as a zero amount is."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from modern_gl.desktop.reports_page.table import Column
from modern_gl.domain.quantity import QUANTITY_SCALE, format_quantity
from modern_gl.i18n import tr


def quantity_text(value: int | None) -> str:
    return format_quantity(value, QUANTITY_SCALE) if value else ""


def quantity_columns(
    parts: list[tuple[str, Callable[[Any], int | None]]],
) -> list[Column]:
    """Columns under «Количество», one per (caption, how many on the row)."""
    return [
        Column(
            tr(title),
            lambda r, get=get: quantity_text(get(r)),
            right=True,
            width=1,
            group=tr("Количество"),
            sort=lambda r, get=get: get(r) or 0,
        )
        for title, get in parts
    ]
