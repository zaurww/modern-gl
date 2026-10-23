"""Postings copied to and from Excel; names the directories lack are added from the grid."""

from __future__ import annotations

from PySide6.QtCore import QPersistentModelIndex, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
)

from modern_gl.desktop.document_page.form import DocumentForm
from modern_gl.desktop.new_cell_value import add_typed_value, offer_new_value
from modern_gl.desktop.postings import (
    DT,
)
from modern_gl.i18n import tr


class ClipboardPart(DocumentForm):
    def paste(self, text: str | None = None) -> None:
        """Lines copied from Excel become postings (see desktop.postings)."""
        if self.model.read_only:
            return
        text = QApplication.clipboard().text() if text is None else text
        if not text.strip():
            return
        self.error.hide()
        cur = self.table.currentIndex()
        row, col = (cur.row(), cur.column()) if cur.isValid() else (0, DT)
        result = self.model.paste(text, row, col, self._shown)
        if result.unknown and self._add_unknown(result.unknown):
            result.unknown = []
        problems = result.errors + [
            tr("нет в справочнике «{kind}»: {text}", kind=self.s.catalog.kinds[k], text=t)
            for _, _, k, t in result.unknown
        ]
        if problems:
            more = len(problems) - 6
            self.show_error(
                "\n".join(problems[:6]) + (f"\n{tr('и ещё {n}', n=more)}" if more > 0 else "")
            )
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def _add_unknown(self, unknown: list[tuple[int, int, int, str]]) -> bool:
        """Names pasted that are not in their directories: add them all in one go."""
        names: dict[tuple[int, str], list[tuple[int, int]]] = {}
        for row, col, kind_id, text in unknown:
            names.setdefault((kind_id, text), []).append((row, col))
        listing = "\n".join(
            f"{self.s.catalog.kinds[kind]}: {text}" for kind, text in list(names)[:12]
        )
        answer = QMessageBox.question(
            self,
            tr("Новые элементы справочников"),
            tr("Этих элементов нет в справочниках. Добавить?\n\n{names}", names=listing),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        # one by one: a new contract belongs to the counterparty its line has by then
        created: dict[tuple[int, str, int | None], int] = {}
        for row, col, kind_id, text in unknown:
            key = (kind_id, text, self.model.owner_at(row, col))
            if key not in created:
                created[key] = add_typed_value(self.s, kind_id, text, key[2], tell=False)
            self.model.setData(self.model.index(row, col), created[key])
        return True

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Проводки скопированы — их можно вставить в Excel"))

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        # Deferred: the cell editor has to be fully closed before a dialog takes focus.
        QTimer.singleShot(0, lambda: self._create_value(index, kind_id, text))

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        offer_new_value(self, self.s, self.table, index, kind_id, text, self.model.owner_at)
