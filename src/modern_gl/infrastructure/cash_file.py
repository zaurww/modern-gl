"""The papers of a cash desk as .xlsx to print and sign (D-new-cash): a cash order —
the order, and under a cut line the receipt for money taken in — and the cash book, a
sheet per day. Forms like the act (`act_file`): merged title cells, thin borders, one
page wide; the words in the company's language of documents (`trd`). The totals of a
day of the cash book are formulas, as reports in Excel (D215)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from modern_gl.domain.dates import ru_date
from modern_gl.domain.money_words import amount_in_words
from modern_gl.i18n import document_language, trd
from modern_gl.infrastructure import paper_form as form
from modern_gl.infrastructure.report_file import MONEY_FORMAT, amount, sheet_name

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet


@dataclass(frozen=True)
class CashDesk:
    """Whose cash desk the papers are of."""

    company: str
    tax_id: str
    name: str  # «Kassa»
    account: str  # «50»
    currency: str  # "" — manat


@dataclass(frozen=True)
class CashOrder:
    """A cash order: in or out, how much, from or to whom, what for."""

    desk: CashDesk
    number: int
    doc_date: str
    incoming: bool  # mədaxil: money came to the cash desk
    corr: str  # the other side's accounts: «62.1», «60, 68»
    party: str  # from whom / to whom
    basis: str  # what for: the document's memo
    amount: int  # minor units of the desk's currency


@dataclass(frozen=True)
class CashLine:
    """A line of a day of the cash book: a document that moved the cash."""

    number: int
    party: str
    corr: str
    money_in: int
    money_out: int


@dataclass
class CashDay:
    """A sheet of the cash book: one day the money moved on."""

    day: str
    opening: int
    lines: list[CashLine] = field(default_factory=list[CashLine])

    @property
    def money_in(self) -> int:
        """Taken in during the day."""
        return sum(line.money_in for line in self.lines)

    @property
    def money_out(self) -> int:
        """Paid out during the day."""
        return sum(line.money_out for line in self.lines)

    @property
    def closing(self) -> int:
        """The balance at the end of the day."""
        return self.opening + self.money_in - self.money_out


@dataclass(frozen=True)
class CashBook:
    """The cash book of a period: its desk and its days."""

    desk: CashDesk
    days: list[CashDay]


def words(order: CashOrder) -> str:
    """The amount in words; a currency desk — the figure and the currency."""
    if order.desk.currency:
        return f"{amount(order.amount):,.2f} {order.desk.currency}".replace(",", " ")
    return amount_in_words(order.amount, document_language())


def write_cash_order_xlsx(order: CashOrder, path: str | Path) -> None:
    """The order on one sheet; an incoming one with its receipt under a cut line."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.worksheets[0]
    title = trd("Приходный кассовый ордер") if order.incoming else trd("Расходный кассовый ордер")
    sheet.title = sheet_name(f"{title} {order.number}")
    form.widths(sheet)
    _order(sheet, order, title)
    if order.incoming:  # the receipt the payer takes away
        sheet.append([])
        sheet.append(["- " * 40])
        sheet.append([])
        _receipt(sheet, order)
    form.page(sheet)
    book.save(str(path))


def write_cash_book_xlsx(cash: CashBook, path: str | Path) -> None:
    """The cash book: a printed page per day."""
    from openpyxl import Workbook
    from openpyxl.worksheet.pagebreak import Break

    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = sheet_name(trd("Кассовая книга"))
    form.widths(sheet)
    for i, day in enumerate(cash.days):
        if i:
            breaks = sheet.row_breaks  # a sheet per day; openpyxl leaves `append` untyped
            breaks.append(Break(id=sheet.max_row))  # pyright: ignore[reportUnknownMemberType]
        _book_day(sheet, cash.desk, day, i + 1)
    form.page(sheet)
    book.calculation.fullCalcOnLoad = True  # the day's totals are formulas
    book.save(str(path))


# ---- the order -----------------------------------------------------------------------


def _order(sheet: Worksheet, order: CashOrder, title: str) -> None:
    desk = order.desk
    form.line(sheet, form.company_line(desk.company, desk.tax_id))
    form.line(sheet, f"{form.upper(title)} № {order.number}", bold=True, size=13)
    form.line(sheet, trd("от {day}", day=ru_date(order.doc_date)))
    sheet.append([])
    debit, credit = (desk.account, order.corr) if order.incoming else (order.corr, desk.account)
    top = sheet.max_row + 1
    sheet.append([trd("Дебет"), trd("Кредит"), trd("Сумма")])
    sheet.append([debit, credit, amount(order.amount)])
    form.boxed(sheet, top, sheet.max_row, 3)
    sheet.cell(sheet.max_row, 3).number_format = MONEY_FORMAT
    sheet.append([])
    who = trd("Принято от") if order.incoming else trd("Выдать")
    form.field(sheet, who, order.party)
    form.field(sheet, trd("Основание"), order.basis)
    form.field(sheet, trd("Сумма прописью"), words(order))
    sheet.append([])
    signers = (
        [trd("Главный бухгалтер"), trd("Кассир")]
        if order.incoming
        else [trd("Руководитель"), trd("Главный бухгалтер"), trd("Получил"), trd("Кассир")]
    )
    for who in signers:
        form.field(sheet, who, "_" * 30)


def _receipt(sheet: Worksheet, order: CashOrder) -> None:
    form.line(sheet, form.company_line(order.desk.company, order.desk.tax_id))
    title = trd("Квитанция к приходному кассовому ордеру № {n}", n=order.number)
    form.line(sheet, title, bold=True)
    form.line(sheet, trd("от {day}", day=ru_date(order.doc_date)))
    form.field(sheet, trd("Принято от"), order.party)
    form.field(sheet, trd("Основание"), order.basis)
    form.field(sheet, trd("Сумма прописью"), words(order))
    form.field(sheet, trd("Главный бухгалтер"), "_" * 30)
    form.field(sheet, trd("Кассир"), "_" * 30)


# ---- the cash book -------------------------------------------------------------------


def _book_day(sheet: Worksheet, desk: CashDesk, day: CashDay, page: int) -> None:
    from openpyxl.styles import Font

    form.line(sheet, form.company_line(desk.company, desk.tax_id))
    form.line(sheet, f"{trd('Кассовая книга')} — {ru_date(day.day)}", bold=True, size=13)
    form.line(sheet, trd("Лист {n}", n=page))
    sheet.append([])
    top = sheet.max_row + 1
    sheet.append(
        [
            trd("№ документа"),
            trd("От кого получено или кому выдано"),
            trd("Корр. счёт"),
            trd("Приход"),
            trd("Расход"),
        ]
    )
    for cell in sheet[top]:
        cell.font = Font(bold=True)
    sheet.append(["", trd("Остаток на начало дня"), "", amount(day.opening), None])
    opening = sheet.max_row
    for line in day.lines:
        sheet.append(
            [
                str(line.number),
                line.party,
                line.corr,
                amount(line.money_in) if line.money_in else None,
                amount(line.money_out) if line.money_out else None,
            ]
        )
    first, last = opening + 1, sheet.max_row
    sheet.append(
        ["", trd("Итого за день"), "", f"=SUM(D{first}:D{last})", f"=SUM(E{first}:E{last})"]
    )
    total = sheet.max_row
    sheet.append(["", trd("Остаток на конец дня"), "", f"=D{opening}+D{total}-E{total}", None])
    for row in (opening, total, sheet.max_row):
        for cell in sheet[row]:
            cell.font = Font(bold=True)
    for row in range(opening, sheet.max_row + 1):
        for col in (4, 5):
            sheet.cell(row, col).number_format = MONEY_FORMAT
    form.boxed(sheet, top, sheet.max_row, 5)
    sheet.append([])
    form.field(sheet, trd("Кассир"), "_" * 30)
    form.field(sheet, trd("Проверил бухгалтер"), "_" * 30)
    sheet.append([])
