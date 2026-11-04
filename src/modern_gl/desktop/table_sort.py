"""A list sorted by a click on a caption: up, down, then as it came (as ОСВ, D190).

For a list of a report model with all its rows read (purchases, sales, the warehouse
documents) — not for a list read page by page (the journal: its order is the reading's).
The order shows in the caption itself («Cəmi ↓»): Qt's arrow sits on a right-aligned
amount's caption."""

from __future__ import annotations

from PySide6.QtWidgets import QTableView

from modern_gl.desktop.reports_page.table import ReportModel


def sortable(view: QTableView) -> None:
    """The captions of `view` sort its rows; the cursor stays on its row."""
    view.horizontalHeader().setSectionsClickable(True)
    view.horizontalHeader().sectionClicked.connect(lambda section: sort_by(view, section))


def sort_by(view: QTableView, section: int) -> None:
    model = view.model()
    if not isinstance(model, ReportModel):
        return
    current = view.currentIndex()
    row = model.rows[current.row()] if current.isValid() else None
    model.sort_by(section)
    fit = getattr(view, "layout_columns", None) or getattr(view, "fit_columns", None)
    if fit is not None:  # the caption with its arrow fits
        fit()
    if row is not None and row in model.rows:
        view.setCurrentIndex(model.index(model.rows.index(row), max(current.column(), 0)))
