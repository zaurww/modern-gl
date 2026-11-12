"""An advance report as an .xlsx to print and sign (D218): who reports,
a line per receipt with its accounts and amount, the total; what was given before the
report, spent, and what is left or overspent — formulas over the table (D215); the
signatures. A form like the cash papers (`paper_form`), in the language of documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from modern_gl.domain.dates import ru_date
from modern_gl.i18n import trd
from modern_gl.infrastructure import paper_form as form
from modern_gl.infrastructure.report_file import MONEY_FORMAT, amount, sheet_name

WIDTHS = (6, 44, 14, 14, 16)  # № · document, content · Dt · Kt · amount


@dataclass(frozen=True)
class AdvancePaperLine:
    """A line of the report: the receipt, its two accounts, the amount."""

    memo: str  # the receipt, what for
    debit: str  # «26 · Yanacaq»
    credit: str  # «71 · Rəşad»
    amount: int


@dataclass(frozen=True)
class AdvancePaper:
    """What the paper says: whose report, what the employee had and spent it on."""

    company: str
    tax_id: str
    number: int
    doc_date: str
    employee: str
    given: int  # what the employee had before the report (minor units; below zero — owed to him)
    lines: list[AdvancePaperLine] = field(default_factory=list[AdvancePaperLine])


def write_advance_report_xlsx(paper: AdvancePaper, path: str | Path) -> None:
    """The report on one sheet, one page wide."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheet = book.worksheets[0]
    title = trd("Авансовый отчёт")
    sheet.title = sheet_name(f"{title} {paper.number}")
    form.widths(sheet, WIDTHS)
    form.line(sheet, form.company_line(paper.company, paper.tax_id))
    form.line(sheet, f"{form.upper(title)} № {paper.number}", bold=True, size=13)
    form.line(sheet, trd("от {day}", day=ru_date(paper.doc_date)))
    form.field(sheet, trd("Подотчётное лицо"), paper.employee)
    sheet.append([])
    top = sheet.max_row + 1
    sheet.append(["№", trd("Документ, содержание"), trd("Дебет"), trd("Кредит"), trd("Сумма")])
    for cell in sheet[top]:
        cell.font = Font(bold=True)
    for n, line in enumerate(paper.lines, start=1):
        sheet.append([n, line.memo, line.debit, line.credit, amount(line.amount)])
    first, last = top + 1, sheet.max_row
    sheet.append(["", trd("Итого"), "", "", f"=SUM(E{first}:E{last})"])
    total = sheet.max_row
    form.boxed(sheet, top, total, 5)
    sheet.append([])
    sheet.append(["", trd("Выдано до отчёта"), "", "", amount(paper.given)])
    given = sheet.max_row
    sheet.append(["", trd("Израсходовано"), "", "", f"=E{total}"])
    spent = sheet.max_row
    overspent = paper.given < sum(line.amount for line in paper.lines)
    left = trd("Перерасход — выдать") if overspent else trd("Остаток — вернуть в кассу")
    sheet.append(["", left, "", "", f"=ABS(E{given}-E{spent})"])
    for row in range(first, sheet.max_row + 1):
        sheet.cell(row, 5).number_format = MONEY_FORMAT
    for row in (total, given, spent, sheet.max_row):
        sheet.cell(row, 2).font = Font(bold=True)
        sheet.cell(row, 5).font = Font(bold=True)
    sheet.append([])
    for who in (trd("Подотчётное лицо"), trd("Бухгалтер"), trd("Утверждаю: руководитель")):
        form.field(sheet, who, "_" * 30)
    form.page(sheet)
    book.calculation.fullCalcOnLoad = True  # the totals are formulas
    book.save(str(path))
