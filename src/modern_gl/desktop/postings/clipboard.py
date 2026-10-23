"""Typed and pasted text becomes the values of the cells; the lines are copied for Excel."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)

from modern_gl.application.table_text import plain_number
from modern_gl.desktop.postings.base import PostingsBase
from modern_gl.desktop.postings.columns import (
    ARITHMETIC,
    CT,
    CURRENCY_AMOUNT_TEXT,
    DT,
    InCurrency,
    PasteResult,
    UnknownValue,
    column_role,
    header_columns,
)
from modern_gl.domain import formula
from modern_gl.domain.currency import (
    parse_rate,
    unit_rate,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class PostingsClipboard(PostingsBase):
    def parse(self, row: int, col: int, text: str):
        """The value for a cell from what was typed or pasted; None for an empty text.
        Raises LookupError / ValueError (UnknownValue for a name not in a directory)."""
        text = text.strip()
        side, pos = column_role(col)
        if side == "invoice":
            return normalize_invoice(text) or ""
        if not text:  # text fields (memo, a template's formula) stay strings
            return "" if side == "memo" or (side == "amount" and self.formulas) else None
        if side in ("debit", "credit") and pos is None:
            return self.catalog.resolve_account(text).id
        if side in ("debit", "credit"):
            return self._parse_subconto(row, col, text)
        if side == "currency":
            return self.catalog.resolve_currency(text).id
        if side == "rate":
            return unit_rate(parse_rate(plain_number(text)))
        if side == "amount" and self.formulas:
            formula.parse(text)  # check now, not when the template is saved
            return text
        if side == "amount" and self.is_currency(row) and (found := self._in_currency(text)):
            return found
        if side in ("amount", "currency_amount"):
            if ARITHMETIC.search(text):  # a small calculator: 1180*18/118
                value = formula.evaluate(text)
            else:
                value = to_minor(plain_number(text))
            if value <= 0:
                raise ValueError(tr("сумма должна быть больше нуля"))
            return value
        return text

    def _parse_subconto(self, row: int, col: int, text: str) -> int:
        kind = self.kind_at(row, col)
        if kind is None:
            raise ValueError(tr("у счёта нет этого субконто: {text}", text=text))
        value = self.catalog.resolve_value(kind, text, self.owner_at(row, col))
        if value is None:
            raise UnknownValue(kind, text)
        return value

    def _in_currency(self, text: str) -> InCurrency | None:
        """ "500 EUR" / "EUR 500" in the amount cell of a line on 60 / 62 / 52."""
        m = CURRENCY_AMOUNT_TEXT.match(text)
        if not m:
            return None
        code = (m["code"] or m["code2"]).upper()
        currency = next((c for c in self.catalog.active_currencies if c.code == code), None)
        if currency is None:
            raise LookupError(tr("валюта «{text}» не найдена", text=code))
        amount = to_minor(plain_number(m["number"] or m["number2"]))
        if amount <= 0:
            raise ValueError(tr("сумма должна быть больше нуля"))
        return InCurrency(currency.id, amount)

    def paste(self, text: str, start_row: int, start_col: int, shown) -> PasteResult:
        """Put lines copied from Excel into the grid (see the module docstring).
        `shown(col)` tells whether a column is visible. A single line goes into the
        current row; more lines fill the current row if it is empty, then new rows."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        cells = [line.split("\t") for line in lines]
        result = PasteResult()
        if not cells:
            return result
        mapping = self.header_columns(cells[0])
        if mapping is not None:
            cells = cells[1:]
        target = start_row
        for n, line in enumerate(cells, start=1):
            if not any(c.strip() for c in line):
                continue
            needs_row = target >= len(self.rows) or not self.rows[target].is_empty()
            if (len(cells) > 1 or target >= len(self.rows)) and needs_row:
                self.insert_row(target)
            if mapping is not None:
                self._paste_by_header(target, line, mapping, n, result)
            else:
                self._paste_in_order(target, line, start_col, shown, n, result)
            result.rows += 1
            target += 1
        self.changed.emit()
        return result

    def header_columns(self, cells: list[str]) -> list[int | None] | None:
        return header_columns(cells)

    def _paste_by_header(self, row, line, mapping, n, result) -> None:
        # accounts first: their subconto columns apply only once the account is known
        order = sorted(
            (i for i, col in enumerate(mapping) if col is not None and i < len(line)),
            key=lambda i: (mapping[i] not in (DT, CT), mapping[i]),
        )
        for i in order:
            if line[i].strip():
                self._paste_cell(row, mapping[i], line[i], n, result)

    def _paste_in_order(self, row, line, start_col, shown, n, result) -> None:
        order = self.column_order()
        at = order.index(start_col)
        for cell in line:
            while at < len(order) and not (shown(order[at]) and self.applies(row, order[at])):
                at += 1
            if at >= len(order):
                if cell.strip():
                    result.errors.append(
                        tr("строка {n}: лишнее значение «{text}»", n=n, text=cell.strip())
                    )
                continue
            if cell.strip():
                self._paste_cell(row, order[at], cell, n, result)
            at += 1

    def _paste_cell(self, row, col, text, n, result) -> None:
        try:
            value = self.parse(row, col, text)
        except UnknownValue as e:
            result.unknown.append((row, col, e.kind_id, e.text))
            return
        except (LookupError, ValueError, TypeError, ValidationError) as e:
            result.errors.append(tr("строка {n}: {error}", n=n, error=str(e).strip("'\"")))
            return
        self.setData(self.index(row, col), value)

    def copy_text(self, shown) -> str:
        """The document as tab-separated lines with a header, for Excel."""
        columns = [c for c in self.column_order() if shown(c)]

        def title(col: int) -> str:
            side, pos = column_role(col)
            if pos is not None:
                return f"{tr('Субконто')} {tr('Дт' if side == 'debit' else 'Кт')} {pos}"
            return str(self.headerData(col, Qt.Orientation.Horizontal))

        lines = ["\t".join(title(c) for c in columns)]
        for r, row in enumerate(self.rows):
            if row.is_empty():
                continue
            values = []
            for c in columns:
                if not self.applies(r, c):
                    values.append("")
                    continue
                value = self.data(self.index(r, c), Qt.ItemDataRole.EditRole)
                values.append("" if value is None else str(value))
            lines.append("\t".join(values))
        return "\n".join(lines) + "\n"
