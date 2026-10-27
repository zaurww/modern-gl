"""Lines copied to and from Excel; names the directories lack are added in one go."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
)

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
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import fold, tr
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
        """Add the new items, warehouses and subconto in one go and put them in place."""
        names: dict[tuple[str, int | None, str], None] = {}
        for _, key, text, kind_id in result.unknown:
            group = ITEM if key == ITEM else WAREHOUSE if kind_id is None else "sc"
            names[(group, kind_id, text)] = None
        titles = {ITEM: tr("Товар"), WAREHOUSE: tr("Склад")}
        listing = "\n".join(
            f"{titles[group] if kind_id is None else self.s.catalog.kinds[kind_id]}: {text}"
            for group, kind_id, text in list(names)[:12]
        )
        items = any(group == ITEM for group, _, _ in names)
        dialog = NewNamesDialog(self.s, listing, items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if items and dialog.account.currentData() is None:
            raise LookupError(tr("В плане счетов нет счёта с субконто Товар и Склад"))
        units: dict[str, int] = {}
        created: dict[tuple, int] = {}
        cid = self.s.company_id
        for row, key, text, kind_id in result.unknown:
            if key == ITEM:
                if (ITEM, text) not in created:
                    unit = self._unit(result.units.get(text) or dialog.unit.currentText(), units)
                    account = int(dialog.account.currentData())
                    created[(ITEM, text)] = self.inventory.add_item(cid, text, unit, account)
                value = created[(ITEM, text)]
            elif kind_id is None:  # a warehouse
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
            self.model.setData(self.model.index(row, self.model.columns.index(key)), value)
        return True

    def _unit(self, text: str, made: dict[str, int]) -> int:
        """A unit by its code or name; a new one if there is none."""
        text = text.strip()
        choices = [(c.id, c.label) for c in unit_choices(self.s.conn, self.s.company_id)]
        try:
            found = resolve_choice(choices, text) if text else None
        except LookupError:
            found = None
        if found is None:
            if not text:
                raise LookupError(tr("Заполните название и единицу"))
            if fold(text) not in made:
                made[fold(text)] = self.inventory.add_unit(self.s.company_id, text, text)
            found = made[fold(text)]
        return found

    def copy(self) -> None:
        QApplication.clipboard().setText(self.model.copy_text(self._shown))
        self.s.notify(tr("Строки скопированы — их можно вставить в Excel"))
