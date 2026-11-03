"""The sheets of «Проводки для Excel»: flat tables a pivot is built on, nothing summed
here. «Проводки» — a line per posting, both sides with their subconto by kind. «Стороны» —
two lines per posting (the Dt side and the Kt side, the amount signed: Dt +, Kt −) and a
line per balance before the period, so one pivot by account gives turnovers and closing
balances alike; the year, month and quarter are columns of their own, since a pivot
groups them more reliably than dates. Every amount is a number, every date a date."""

from __future__ import annotations

from datetime import date, timedelta

from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.report_file import ReportColumn, ReportRow, ReportTable
from modern_gl.reporting.flat_postings import FlatLine, FlatPostings, Kind, Side

CLASS_NAMES = {
    "asset": N_("Активы"),
    "liability": N_("Обязательства"),
    "equity": N_("Капитал"),
    "revenue": N_("Доходы"),
    "expense": N_("Расходы"),
}


def flat_tables(flat: FlatPostings, about: list[tuple[str, str]]) -> list[ReportTable]:
    """The two sheets, «Проводки» first; `about` goes to «Параметры»."""
    postings = ReportTable(tr("Проводки"), _posting_columns(flat.kinds), [], about, as_table=True)
    postings.rows = [ReportRow(_posting_cells(line, flat.kinds)) for line in flat.lines]
    sides = ReportTable(tr("Стороны"), _side_columns(flat.kinds), [], about, as_table=True)
    before = (date.fromisoformat(flat.date_from) - timedelta(days=1)).isoformat()
    sides.rows = [
        ReportRow(
            [
                *_when(before),
                None,
                "",
                tr("Остаток на начало"),
                tr("Остаток"),
                "",
                *_side_cells(o.side, flat.kinds),
                "",
                "",
                o.net,
                o.net if o.net > 0 else None,
                -o.net if o.net < 0 else None,
                "",
                None,
                "",
                "",
                "",
                None,
            ]
        )
        for o in flat.opening
    ]
    for line in flat.lines:
        sides.rows.append(ReportRow(_side_row(line, flat.kinds, "Дт")))
        sides.rows.append(ReportRow(_side_row(line, flat.kinds, "Кт")))
    return [postings, sides]


def _when_columns() -> list[ReportColumn]:
    return [
        ReportColumn(tr("Дата"), date=True),
        ReportColumn(tr("Год"), number=True),
        ReportColumn(tr("Месяц")),
        ReportColumn(tr("Квартал")),
    ]


def _when(iso: str) -> list[object]:
    year, month = int(iso[:4]), int(iso[5:7])
    return [iso, year, iso[:7], f"{year}-Q{(month - 1) // 3 + 1}"]


def _account_columns(side: str) -> list[ReportColumn]:
    return [
        ReportColumn(tr("Счёт"), group=side),
        ReportColumn(tr("Название"), group=side),
        ReportColumn(tr("Класс"), group=side),
        ReportColumn(tr("Счёт верхнего уровня"), group=side),
    ]


def _kind_columns(kinds: list[Kind], side: str = "") -> list[ReportColumn]:
    columns = []
    for k in kinds:
        columns.append(ReportColumn(k.name, group=side))
        if k.folders:
            columns.append(ReportColumn(f"{k.name} · {tr('папка')}", group=side))
        if k.tags:
            columns.append(ReportColumn(f"{k.name} · {tr('теги')}", group=side))
    return columns


def _side_cells(side: Side, kinds: list[Kind]) -> list[object]:
    """The account and its subconto by kind — as `_account_columns` + `_kind_columns`."""
    cells: list[object] = [
        side.code,
        side.name,
        tr(CLASS_NAMES[side.account_class]) if side.account_class in CLASS_NAMES else "",
        " ".join(filter(None, (side.top_code, side.top_name))),
    ]
    for k in kinds:
        value = side.value(k.id)
        cells.append(value.name if value else "")
        if k.folders:
            cells.append(value.folder if value else "")
        if k.tags:
            cells.append(value.tags if value else "")
    return cells


def _posting_columns(kinds: list[Kind]) -> list[ReportColumn]:
    return [
        *_when_columns(),
        ReportColumn(tr("№"), number=True),
        ReportColumn(tr("Документ")),
        ReportColumn(tr("Содержание")),
        ReportColumn(tr("Содержание строки")),
        *_account_columns(tr("Дт")),
        *_kind_columns(kinds, tr("Дт")),
        *_account_columns(tr("Кт")),
        *_kind_columns(kinds, tr("Кт")),
        ReportColumn(tr("Сумма"), money=True),
        ReportColumn(tr("Валюта")),
        ReportColumn(tr("Сумма в валюте"), money=True),
        ReportColumn(tr("Книга")),
        ReportColumn("E-qaimə"),
        ReportColumn(tr("Вид e-qaimə")),
        ReportColumn(tr("Провёл")),
        ReportColumn(tr("ID документа"), number=True),
    ]


def _posting_cells(line: FlatLine, kinds: list[Kind]) -> list[object]:
    return [
        *_when(line.doc_date),
        line.number,
        line.source,
        line.memo,
        line.line_memo,
        *_side_cells(line.debit, kinds),
        *_side_cells(line.credit, kinds),
        line.amount,
        line.currency,
        line.currency_amount,
        line.layer,
        line.invoice,
        line.invoice_kind,
        line.author,
        line.document_id,
    ]


def _side_columns(kinds: list[Kind]) -> list[ReportColumn]:
    return [
        *_when_columns(),
        ReportColumn(tr("№"), number=True),
        ReportColumn(tr("Документ")),
        ReportColumn(tr("Содержание")),
        ReportColumn(tr("Вид строки")),
        ReportColumn(tr("Сторона")),
        *_account_columns(""),
        *_kind_columns(kinds),
        ReportColumn(tr("Корр. счёт")),
        ReportColumn(tr("Корр. название")),
        ReportColumn(tr("Сумма"), money=True),
        ReportColumn(tr("Дт"), money=True),
        ReportColumn(tr("Кт"), money=True),
        ReportColumn(tr("Валюта")),
        ReportColumn(tr("Сумма в валюте"), money=True),
        ReportColumn(tr("Книга")),
        ReportColumn("E-qaimə"),
        ReportColumn(tr("Провёл")),
        ReportColumn(tr("ID документа"), number=True),
    ]


def _side_row(line: FlatLine, kinds: list[Kind], side: str) -> list[object]:
    """A line of «Стороны»: the Dt side (+) or the Kt side (−) of a posting."""
    debit = side == "Дт"
    own, corr = (line.debit, line.credit) if debit else (line.credit, line.debit)
    sign = 1 if debit else -1
    return [
        *_when(line.doc_date),
        line.number,
        line.source,
        line.memo,
        tr("Проводка"),
        tr("Дт") if debit else tr("Кт"),
        *_side_cells(own, kinds),
        corr.code,
        corr.name,
        sign * line.amount,
        line.amount if debit else None,
        None if debit else line.amount,
        line.currency,
        sign * line.currency_amount if line.currency_amount is not None else None,
        line.layer,
        line.invoice,
        line.author,
        line.document_id,
    ]
