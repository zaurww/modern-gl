"""Lines copied to and from Excel; names the directories lack are added in one go."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
)

from modern_gl.application.inventory import NewItem
from modern_gl.desktop.cell_editing import resolve_choice
from modern_gl.desktop.inventory_document_page.columns import (
    ITEM,
    WAREHOUSE,
    InventoryPaste,
)
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.inventory_document_page.lines_table import (
    NewNamesDialog,
)
from modern_gl.desktop.inventory_document_page.new_items_dialog import NewItemsDialog
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    unit_choices,
)


class ClipboardPart(InventoryDocumentForm):
    def paste(self, text: str | None = None) -> None:
        """Lines copied from Excel become lines of the document."""
        if self.model.read_only or self.doc_type == "landed_cost":
            return
        text = QApplication.clipboard().text() if text is None else text
        if not text.strip():
            return
        self.error.hide()
        current = self.table.currentIndex()
        row, column = (current.row(), current.column()) if current.isValid() else (0, 0)
        result = self._paste_into(text, row, column)
        problems = list(result.errors)
        if result.unknown:
            try:
                added = self._add_unknown(result)
            except (LedgerError, LookupError) as exc:
                added, problems = False, [*problems, str(exc)]
            if not added:
                problems += [
                    tr("нет в справочнике: {text}", text=text) for _, _, text, _ in result.unknown
                ]
        if problems:
            more = len(problems) - 6
            self.show_error(
                "\n".join(problems[:6]) + (f"\n{tr('и ещё {n}', n=more)}" if more > 0 else "")
            )
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def _paste_into(self, text: str, row: int, column: int) -> InventoryPaste:
        """The lines pasted from `row`; one value copied (a cost item) goes into every
        line selected in the column, as in Excel."""
        current = self.model.index(row, column)
        value = text.strip("\r\n")
        one = "\t" not in value and "\n" not in value  # one cell copied, not lines
        rows = self.table.selected_rows(current) if one else []
        if len(rows) < 2:
            return self.model.paste(text, row, column, self._shown)
        result = InventoryPaste()
        for target in rows:
            part = self.model.paste(text, target, column, self._shown)
            result.errors += part.errors
            result.unknown += part.unknown
            result.units.update(part.units)
        result.rows = len(rows)
        return result

    def _add_unknown(self, result: InventoryPaste) -> bool:
        """The names the lists lack, in one window. Warehouses and subconto are added at
        once; an item stays a name on its lines until the document is saved (D209)."""
        names: dict[tuple[str, int | None, str], None] = {}
        for _, key, text, kind_id in result.unknown:
            group = ITEM if key == ITEM else WAREHOUSE if kind_id is None else "sc"
            names[(group, kind_id, text)] = None
        titles = {ITEM: tr("Товар"), WAREHOUSE: tr("Склад")}
        listing = "\n".join(
            f"{titles[group] if kind_id is None else self.s.catalog.kinds[kind_id]}: {text}"
            for group, kind_id, text in list(names)[:12]
        )
        if len(names) > 12:
            listing += f"\n{tr('и ещё {n}', n=len(names) - 12)}"
        new_names = [text for group, _, text in names if group == ITEM]
        dialog = (
            NewItemsDialog(self.s, listing, new_names, self.model.choices(0, ITEM), self)
            if new_names
            else NewNamesDialog(self.s, listing, False, self)
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if new_names and dialog.account.currentData() is None:
            raise LookupError(tr("В плане счетов нет счёта с субконто Товар и Склад"))
        created: dict[tuple, int] = {}
        for row, key, text, kind_id in result.unknown:
            if key == ITEM:
                value = self._item_of(text, result, dialog, created)
            else:
                value = self._add_named(row, key, text, kind_id, created)
            self.model.setData(self.model.index(row, self.model.columns.index(key)), value)
        return True

    def _item_of(self, text: str, result, dialog, created: dict[tuple, int]) -> int:
        """The item picked in the window for a new name, else a new one on the lines."""
        if (ITEM, text) not in created:
            found = dialog.picked(text)
            if found is None:
                unit, shown = self._unit(result.units.get(text) or dialog.unit.currentText())
                item = NewItem(text, unit, int(dialog.account.currentData()))
                found = self.model.add_new_item(item, shown)
            created[(ITEM, text)] = found
        return created[(ITEM, text)]

    def _add_named(self, row: int, key: str, text: str, kind_id, created: dict[tuple, int]) -> int:
        """A warehouse or a subconto element: added now, the line takes it."""
        cid = self.s.company_id
        if kind_id is None:
            if (WAREHOUSE, text) not in created:
                created[(WAREHOUSE, text)] = self.inventory.add_warehouse(cid, text)
            value = created[(WAREHOUSE, text)]
        else:  # a contract belongs to the counterparty its line has by then
            owner = self.model.owner_at(row, key)
            if (kind_id, text, owner) not in created:
                value_id = self.s.ledger.add_subconto_value(cid, kind_id, text, owner_id=owner)
                self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner)
                created[(kind_id, text, owner)] = value_id
            value = created[(kind_id, text, owner)]
        self.s.catalog.reload()
        self.model.refresh_choices()
        return value

    def _unit(self, text: str) -> tuple[int | str, str]:
        """A unit by its code or name, else the text of a new one; and what the line shows."""
        text = text.strip()
        choices = [(c.id, c.label) for c in unit_choices(self.s.conn, self.s.company_id)]
        try:
            found = resolve_choice(choices, text) if text else None
        except LookupError:
            found = None
        if found is not None:
            return found, dict(choices)[found].split("  ", 1)[0]
        if not text:
            raise LookupError(tr("Заполните название и единицу"))
        return text, text

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Строки скопированы — их можно вставить в Excel"))
