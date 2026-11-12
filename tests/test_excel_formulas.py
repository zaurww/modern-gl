"""Excel with formulas: a total is SUBTOTAL of its lines, a closing balance is the opening
plus the turnovers — and only where that gives the report's own figure (figures by hand)."""

from __future__ import annotations

import re
from decimal import Decimal

import openpyxl
import pytest

from modern_gl.infrastructure.report_file import ReportColumn, ReportRow, ReportTable, write_xlsx

NAME = ReportColumn("Счёт")


def money(title: str, role: str = "") -> ReportColumn:
    return ReportColumn(title, money=True, role=role)


def written(table: ReportTable, tmp_path) -> list[list[object]]:
    path = tmp_path / "r.xlsx"
    write_xlsx(table, path)
    book = openpyxl.load_workbook(path)
    assert book.calculation.fullCalcOnLoad  # Excel works the formulas out on opening
    return [list(r) for r in book.worksheets[0].iter_rows(min_row=2, values_only=True)]


def figure(sheet: list[list[object]], cell: str) -> Decimal:
    """What Excel shows in a cell: its number, or its formula worked out (SUBTOTAL leaves
    out the SUBTOTALs in its range, as Excel does)."""
    col, row = ord(cell[0]) - ord("A"), int(cell[1:]) - 2
    value = sheet[row][col]
    if not isinstance(value, str) or not value.startswith("="):
        return Decimal(0) if value in (None, "") else Decimal(str(value))

    def subtotal(m: re.Match[str]) -> str:
        c, first, last = m.group(1), int(m.group(2)), int(m.group(4))
        total = Decimal(0)
        for r in range(first, last + 1):
            inner = sheet[r - 2][ord(c) - ord("A")]
            if not (isinstance(inner, str) and inner.startswith("=SUBTOTAL")):
                total += figure(sheet, f"{c}{r}")
        return str(total)

    text = re.sub(r"SUBTOTAL\(9,([A-Z])(\d+):([A-Z])(\d+)\)", subtotal, value[1:])
    return worked_out(re.sub(r"\b[A-Z]\d+\b", lambda m: str(figure(sheet, m.group(0))), text))


def worked_out(text: str) -> Decimal:
    """MAX(0,…), -(…) and figures added and taken away — what our formulas are made of."""
    if text.startswith("MAX(0,") and text.endswith(")"):
        return max(Decimal(0), worked_out(text[6:-1]))
    if text.startswith("-(") and text.endswith(")"):
        return -worked_out(text[2:-1])
    terms = re.findall(r"([+-]?)(-?\d+(?:\.\d+)?)", text)
    return sum((Decimal(n) * (-1 if s == "-" else 1) for s, n in terms), Decimal(0))


def test_a_group_and_the_grand_total_are_subtotals(tmp_path):
    # Расходы 100 + 200 = 300; Доходы 500; Итого 100 + 200 + 500 = 800 (groups left out)
    table = ReportTable(
        "Отчёт",
        [NAME, money("Сумма")],
        [
            ReportRow(["Расходы", 30_000], 0, bold=True),
            ReportRow(["Аренда", 10_000], 1),
            ReportRow(["Связь", 20_000], 1),
            ReportRow(["Доходы", 50_000], 0, bold=True),
            ReportRow(["Продажи", 50_000], 1),
            ReportRow(["Итого", 80_000], 0, bold=True, total=True),
        ],
    )
    sheet = written(table, tmp_path)
    assert [r[1] for r in sheet] == [
        "=SUBTOTAL(9,B3:B4)",
        100,
        200,
        "=SUBTOTAL(9,B6:B6)",
        500,
        "=SUBTOTAL(9,B2:B6)",
    ]
    assert figure(sheet, "B7") == 800


def test_nested_subtotals_add_up_once(tmp_path):
    # 60 = 60.1 (150 + 250 = 400) + 60.2 (200) = 600
    table = ReportTable(
        "ОСВ",
        [NAME, money("Сумма")],
        [
            ReportRow(["60", 60_000], 0),
            ReportRow(["60.1", 40_000], 1),
            ReportRow(["A", 15_000], 2),
            ReportRow(["B", 25_000], 2),
            ReportRow(["60.2", 20_000], 1),
        ],
    )
    sheet = written(table, tmp_path)
    assert sheet[0][1] == "=SUBTOTAL(9,B3:B6)"
    assert sheet[1][1] == "=SUBTOTAL(9,B4:B5)"
    assert sheet[4][1] == 200  # a line without lines under it stays a number
    assert figure(sheet, "B2") == 600


def test_what_is_not_a_sum_stays_a_number(tmp_path):
    # a profit 1000 over revenue 1500 and costs 500: 1500 + 500 ≠ 1000; a total
    # without anything above it; an empty group
    table = ReportTable(
        "ОПиУ",
        [NAME, money("Сумма")],
        [
            ReportRow(["Прибыль", 100_000], 0, bold=True),
            ReportRow(["Выручка", 150_000], 1),
            ReportRow(["Расходы", 50_000], 1),
            ReportRow(["Пусто", None], 0, bold=True),
            ReportRow(["Ничего", None], 1),
        ],
    )
    sheet = written(table, tmp_path)
    assert [r[1] for r in sheet] == [1000, 1500, 500, None, None]


def test_a_bold_line_that_is_not_a_total_is_not_summed(tmp_path):
    # account 10 is bold, the line above is equal to it — still not its total
    table = ReportTable(
        "ОСВ",
        [NAME, money("Сумма")],
        [ReportRow(["01", 5_000], 0, bold=True), ReportRow(["10", 5_000], 0, bold=True)],
    )
    assert [r[1] for r in written(table, tmp_path)] == [50, 50]


def test_a_closing_balance_in_one_column(tmp_path):
    # 1000 + 500 − 300 = 1200; the second line's closing 999 is not that — a number
    columns = [
        NAME,
        money("Сальдо на начало", "opening"),
        money("Дт", "turnover_dt"),
        money("Кт", "turnover_ct"),
        money("Сальдо на конец", "closing"),
    ]
    table = ReportTable(
        "ОСВ",
        columns,
        [
            ReportRow(["50", 100_000, 50_000, 30_000, 120_000]),
            ReportRow(["51", 100_000, 50_000, 30_000, 99_900]),
        ],
    )
    sheet = written(table, tmp_path)
    assert sheet[0][4] == "=B2+C2-D2"
    assert sheet[1][4] == 999
    assert figure(sheet, "E2") == 1200


def test_a_closing_balance_on_its_side(tmp_path):
    # 60: −500 + 800 − 100 = 200 Дт; 62: 0 + 100 − 400 = −300 → 300 Кт;
    # 76 shown on both sides (expanded) is not one balance — numbers
    columns = [
        NAME,
        *(
            money(t, r)
            for t, r in [
                ("Нач Дт", "opening_dt"),
                ("Нач Кт", "opening_ct"),
                ("Об Дт", "turnover_dt"),
                ("Об Кт", "turnover_ct"),
                ("Кон Дт", "closing_dt"),
                ("Кон Кт", "closing_ct"),
            ]
        ),
    ]
    table = ReportTable(
        "ОСВ",
        columns,
        [
            ReportRow(["60", 0, 50_000, 80_000, 10_000, 20_000, 0]),
            ReportRow(["62", 0, 0, 10_000, 40_000, 0, 30_000]),
            ReportRow(["76", 0, 0, 30_000, 10_000, 30_000, 10_000]),
        ],
    )
    sheet = written(table, tmp_path)
    assert sheet[0][5] == "=MAX(0,B2+D2-C2-E2)"
    assert sheet[0][6] == "=MAX(0,-(B2+D2-C2-E2))"
    assert (figure(sheet, "F2"), figure(sheet, "G2")) == (200, 0)
    assert (figure(sheet, "F3"), figure(sheet, "G3")) == (0, 300)
    assert sheet[2][5:] == [300, 100]


def test_a_file_without_formulas_has_numbers(tmp_path):
    table = ReportTable(
        "Отчёт",
        [NAME, money("Сумма")],
        [ReportRow(["Итого", 100], 0, bold=True), ReportRow(["a", 100], 1)],
        with_formulas=False,
    )
    assert [r[1] for r in written(table, tmp_path)] == [1, 1]


@pytest.fixture
def window(statements_window):
    return statements_window


@pytest.mark.parametrize("net", [False, True])
def test_every_formula_of_the_trial_balance_is_its_figure(window, qtbot, tmp_path, net):
    """The real trial balance, both ways of balances: Excel's figures are the report's."""
    from modern_gl.desktop.reports_page import OsvPage
    from modern_gl.desktop.reports_page.export import report_table

    page = OsvPage(window.session)
    qtbot.addWidget(page)
    if net != page.net:
        page.toggle_net()
    table = report_table(page.model, "ОСВ", [])
    sheet = written(table, tmp_path)
    formulas = 0
    for i, row in enumerate(table.rows):
        for j, c in enumerate(table.columns):
            if c.money and isinstance(sheet[i][j], str):
                formulas += 1
                expected = Decimal(row.cells[j] or 0) / 100  # type: ignore[arg-type]
                assert figure(sheet, f"{chr(ord('A') + j)}{i + 2}") == expected
    assert formulas > 0
