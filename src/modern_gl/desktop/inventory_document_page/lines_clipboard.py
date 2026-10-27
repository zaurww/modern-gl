"""Lines copied to and from Excel: pasted text becomes the cells of the lines."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)

from modern_gl.application.inventory import (
    to_quantity,
)
from modern_gl.application.table_text import plain_number
from modern_gl.desktop.cell_editing import resolve_choice
from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    EXPENSE,
    EXPENSE_MONTH,
    HEADERS,
    ITEM,
    LIST_KEYS,
    MEMO,
    PASTE_ORDER,
    PRICE,
    QUANTITY,
    SALE_KEYS,
    SC_KEYS,
    SUBCONTO_KEYS,
    TO_WAREHOUSE,
    UNIT,
    VAT,
    WAREHOUSE,
    InventoryPaste,
    UnknownNameError,
    paste_columns,
)
from modern_gl.desktop.inventory_document_page.lines_base import InventoryLinesBase
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import N_, tr


class LinesClipboard(InventoryLinesBase):
    def parse(self, row_index: int, key: str, text: str):
        """The value of a cell from pasted text. Raises UnknownNameError for a new name."""
        text = text.strip()
        if key in {ITEM, WAREHOUSE, TO_WAREHOUSE}:
            value = resolve_choice(self.choices(row_index, key), text)
            if value is None:
                raise UnknownNameError(key, text)
            return value
        if key in {ACCOUNT, EXPENSE}:
            return self.s.catalog.resolve_account(text).id
        if key == EXPENSE_MONTH:
            return self.month_code_of(text)
        if key in SUBCONTO_KEYS:
            kind_id = self.kind_at(row_index, key)
            if kind_id is None:
                raise ValueError(tr("у счёта нет этого субконто: {text}", text=text))
            value = self.s.catalog.resolve_value(kind_id, text, self.owner_at(row_index, key))
            if value is None:
                raise UnknownNameError(key, text, kind_id)
            return value
        if key == QUANTITY:
            value = to_quantity(plain_number(text))
        elif key in {PRICE, AMOUNT, VAT, CURRENCY_AMOUNT}:
            value = to_minor(plain_number(text))
            if key == VAT and value == 0:
                return 0
        else:
            return text
        if value <= 0:
            raise ValueError(tr("должно быть больше нуля: {text}", text=text))
        return value

    def paste(self, text: str, start_row: int, start_column: int, shown) -> InventoryPaste:
        """Lines copied from Excel become lines of the document: by the header line if
        there is one (Товар, Количество, Цена, Сумма… in any order), else in the order
        of the table from the current column. `shown(column)` tells if it is visible.
        One line goes into the current row; more fill it if empty, then new rows."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        cells = [line.split("\t") for line in lines]
        result = InventoryPaste()
        if not cells or self.read_only:
            return result
        mapping = paste_columns(cells[0], self.columns)
        if mapping is not None:
            cells = cells[1:]
        target = start_row
        for n, line in enumerate(cells, start=1):
            if not any(cell.strip() for cell in line):
                continue
            needs_row = target >= len(self.rows) or not self.rows[target].is_empty()
            if (len(cells) > 1 or target >= len(self.rows)) and needs_row:
                self.insert_row(target)
            keys = mapping or self._columns_in_order(target, start_column, shown)
            pasted = {
                key: cell.strip()
                for key, cell in zip(keys, line, strict=False)
                if key is not None and cell.strip()
            }
            extra = [cell.strip() for cell in line[len(keys) :] if cell.strip()]
            if extra:
                result.errors.append(tr("строка {n}: лишнее значение «{text}»", n=n, text=extra[0]))
            self._paste_line(target, pasted, n, result)
            result.rows += 1
            target += 1
        self.changed.emit()
        return result

    def _columns_in_order(self, row_index: int, start: int, shown) -> list[str]:
        """Without a header the cells follow the visible columns of the table
        (subconto only as far as the line's account has them)."""
        return [
            key
            for column, key in enumerate(self.columns)
            if column >= start
            and shown(column)
            and (self.editable(key) or key == UNIT)
            and self.applies(row_index, key)
        ]

    def _paste_line(self, row_index: int, pasted: dict[str, str], n: int, result) -> None:
        for key in PASTE_ORDER:
            if key not in pasted or not self.editable(key):
                continue
            if key == PRICE and AMOUNT in pasted:
                continue  # the amount is exact; a price is rounded
            try:
                value = self.parse(row_index, key, pasted[key])
                self.setData(self.index(row_index, self.columns.index(key)), value)
            except UnknownNameError as e:
                result.unknown.append((row_index, key, e.text, e.kind_id))
                if key == ITEM and UNIT in pasted:
                    result.units[e.text] = pasted[UNIT]
            except (LookupError, ValueError, TypeError, LedgerError) as e:
                result.errors.append(tr("строка {n}: {error}", n=n, error=str(e).strip("'\"")))
        if MEMO in pasted and self.editable(MEMO):
            self.setData(self.index(row_index, self.columns.index(MEMO)), pasted[MEMO])
        row = self.rows[row_index]
        if row.warehouse_id is None and len(self.warehouses) == 1:  # the only one there is
            row.warehouse_id = next(iter(self.warehouses))

    def copy_text(self, shown) -> str:
        """The lines as tab-separated text with a header, for Excel."""
        columns = [c for c in range(len(self.columns)) if shown(c)]

        def title(key: str) -> str:
            if key in SALE_KEYS:
                return str(self.headerData(self.columns.index(key), Qt.Orientation.Horizontal))
            if key in SUBCONTO_KEYS:
                caption = "Субконто" if key in SC_KEYS else N_("Субконто затрат")
                return f"{tr(caption)} {key[-1]}"
            return tr(HEADERS[key])

        lines = ["\t".join(title(self.columns[c]) for c in columns)]
        for r, row in enumerate(self.rows):
            if row.is_empty():
                continue
            values = []
            for c in columns:
                key = self.columns[c]
                if key in LIST_KEYS:
                    filled = self._edit_value(r, key) is not None
                    values.append(self._display_text(r, key) if filled else "")
                else:
                    values.append(str(self._edit_value(r, key) or ""))
            lines.append("\t".join(values))
        return "\n".join(lines) + "\n"
