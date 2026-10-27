"""The fixed assets (intangibles) of a purchase's lines, each line its own, named by the
line: «Объекты по названиям строк» makes them at once (D172)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class LineObjectsPart(InventoryDocumentForm):
    def _connect_objects(self) -> None:
        self.btn_objects.clicked.connect(self._make_objects)

    def _show_objects_button(self) -> None:
        """Shown while a line on a fixed asset account (01, 08) has no asset yet."""
        self.btn_objects.setVisible(
            not self.model.read_only and bool(self.model.lines_without_object())
        )

    def _make_objects(self) -> None:
        """The lines checked get an asset each, named by the line; a name the directory
        has is that asset. A line left unchecked (an installation) is chosen by hand."""
        model = self.model
        found = model.lines_without_object()
        if not found:
            return
        dialog = NewNamesDialog(
            self.s,
            "",
            False,
            self,
            lines=[(row, name) for row, name, _key in found],
            chosen={row for row, _name, _key in found},
            wording=(
                tr("Объекты по названиям строк"),
                tr("Отмеченные строки получат каждая свой объект — по названию строки:"),
                tr("Создать объекты"),
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.checked_rows():
            return
        checked = set(dialog.checked_rows())
        chosen = [(row, name, key) for row, name, key in found if row in checked]
        by_kind: dict[int, list[tuple[int, str, str]]] = {}
        for row, name, key in chosen:
            kind = model.kind_at(row, key)
            assert kind is not None  # a line without an object has the directory
            by_kind.setdefault(kind, []).append((row, name, key))
        try:
            for kind, lines in by_kind.items():
                ids = self.s.ledger.add_named_values(
                    self.s.company_id, kind, [name for _row, name, _key in lines]
                )
                self.s.catalog.reload()
                for (row, _name, key), value in zip(lines, ids, strict=True):
                    model.setData(model.index(row, model.columns.index(key)), value)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.s.notify(tr("Объекты по названиям строк: {n}", n=len(chosen)))
