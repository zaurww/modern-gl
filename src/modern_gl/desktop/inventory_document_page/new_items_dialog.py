"""Names pasted that the item list lacks: each is a new item or, if one looks like it, that
item. Nothing is written here: a new name stays on the lines until the document is saved."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QWidget,
)

from modern_gl.application.inventory.similar import similar_choices
from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
from modern_gl.desktop.session import Session
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import hidden_item_names

MOST_HEIGHT = 260


class NewItemsDialog(NewNamesDialog):
    def __init__(
        self,
        session: Session,
        listing: str,
        names: list[str],
        items: list[tuple[int, str]],
        parent=None,
    ) -> None:
        """`names` — the new ones; `items` — (id, label) of the items they are compared to."""
        super().__init__(session, listing, True, parent)
        self.pickers: dict[str, QComboBox] = {}
        form = self.layout()
        assert isinstance(form, QFormLayout)
        at = 1  # under the text of the window
        like = [(name, found) for name in names if (found := similar_choices(name, items))]
        if like:
            form.insertRow(at, QLabel(tr("Похожие уже есть. Это они или новые товары?")))
            form.insertRow(at + 1, self._choices(like))
            at += 2
        hidden = [(0, name) for name in hidden_item_names(session.conn, session.company_id)]
        twins = [text for name in names for _, text in similar_choices(name, hidden)]
        if twins:
            note = QLabel(
                tr(
                    "Похожие есть среди скрытых товаров: {names}",
                    names=", ".join(dict.fromkeys(twins)),
                )
            )
            note.setWordWrap(True)
            form.insertRow(at, note)

    def _choices(self, like: list[tuple[str, list[tuple[int, str]]]]) -> QScrollArea:
        rows = QWidget()
        form = QFormLayout(rows)
        for name, found in like:
            picker = QComboBox()
            picker.addItem(tr("Новый товар"), None)
            for item_id, label in found:
                picker.addItem(label, item_id)
            self.pickers[name] = picker
            form.addRow(name, picker)
        area = QScrollArea()
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setWidget(rows)
        area.setMaximumHeight(MOST_HEIGHT)
        return area

    def picked(self, name: str) -> int | None:
        """The item chosen for a name; None — a new one."""
        picker = self.pickers.get(name)
        return None if picker is None else picker.currentData()
