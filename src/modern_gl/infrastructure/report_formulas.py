"""Formulas in a report file (Excel with formulas, D215): a total is `SUBTOTAL` of its lines, a
closing balance is the opening plus the turnovers — so a figure changed in Excel moves
what it makes. A formula is written only where it gives exactly the figure the report
shows; elsewhere (a total that is not a sum, a balance of an account on both sides) the
cell keeps its number, so the file is never wrong.

`SUBTOTAL(9, …)` leaves out the `SUBTOTAL`s inside its range, as a report adds up: a
group's total over its lines with their own subtotals, the grand total over everything
above. What a formula would give is worked out here the same way before it is chosen."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

FIRST_ROW = 2  # row 1 is the header

# the balance columns of a trial balance a closing is worked out of (`ReportColumn.role`)
NET = ("opening", "turnover_dt", "turnover_ct", "closing")
PAIR = ("opening_dt", "opening_ct", "turnover_dt", "turnover_ct", "closing_dt", "closing_ct")


class Line(Protocol):
    """A line of a report (`ReportRow`): its cells, depth and whether it is a total."""

    cells: list[object]
    level: int
    total: bool


type Letter = Callable[[int], str]  # column index (0-based) -> «C»


def formulas(
    roles: Sequence[str], money: Sequence[bool], rows: Sequence[Line], letter: Letter
) -> dict[tuple[int, int], str]:
    """{(row index, column index): «=…»} for the cells that can be formulas."""
    found: dict[tuple[int, int], str] = {}
    subtotals: set[tuple[int, int]] = set()  # what a SUBTOTAL around them leaves out
    columns = [j for j, m in enumerate(money) if m]
    for i, first, last in _ranges(rows):
        for j in columns:
            value = rows[i].cells[j]
            if not isinstance(value, int) or first > last:
                continue
            total = sum(
                v
                for k in range(first, last + 1)
                if (k, j) not in subtotals and isinstance(v := rows[k].cells[j], int)
            )
            if total == value:
                found[i, j] = (
                    f"=SUBTOTAL(9,{letter(j)}{first + FIRST_ROW}:{letter(j)}{last + FIRST_ROW})"
                )
                subtotals.add((i, j))
    _balances(roles, rows, letter, found)
    return found


def _ranges(rows: Sequence[Line]) -> list[tuple[int, int, int]]:
    """(row, first, last) of the lines each total adds up, inner ones first: a line's
    deeper lines right under it; a top total line with none — the lines above it, since
    the previous such total (a section) or from the top."""
    groups: list[tuple[int, int, int]] = []
    totals: list[tuple[int, int, int]] = []
    start = 0
    for i, r in enumerate(rows):
        last = i
        while last + 1 < len(rows) and rows[last + 1].level > r.level:
            last += 1
        if last > i:
            groups.append((i, i + 1, last))
        elif r.total and r.level == 0:
            totals.append((i, start, i - 1))
            start = i + 1
    groups.sort(key=lambda g: -rows[g[0]].level)  # the deepest first
    return groups + totals


def _balances(
    roles: Sequence[str], rows: Sequence[Line], letter: Letter, found: dict[tuple[int, int], str]
) -> None:
    """A closing balance of a line as its opening plus the turnovers, when it is that."""
    at = {r: j for j, r in enumerate(roles) if r}
    for i, row in enumerate(rows):
        if all(r in at for r in NET):
            o, d, c, z = (at[r] for r in NET)
            v = _ints(row.cells, o, d, c, z)
            if v and v[0] + v[1] - v[2] == v[3] and (i, z) not in found:
                found[i, z] = f"={_at(letter, o, i)}+{_at(letter, d, i)}-{_at(letter, c, i)}"
        if all(r in at for r in PAIR):
            od, oc, d, c, zd, zc = (at[r] for r in PAIR)
            v = _ints(row.cells, od, oc, d, c, zd, zc)
            if not v:
                continue
            net = v[0] - v[1] + v[2] - v[3]
            if (v[4], v[5]) != (max(net, 0), max(-net, 0)):
                continue
            plus = f"{_at(letter, od, i)}+{_at(letter, d, i)}"
            less = f"-{_at(letter, oc, i)}-{_at(letter, c, i)}"
            if (i, zd) not in found:
                found[i, zd] = f"=MAX(0,{plus}{less})"
            if (i, zc) not in found:
                found[i, zc] = f"=MAX(0,-({plus}{less}))"


def _ints(cells: list[object], *js: int) -> list[int] | None:
    """The cells as figures; None when one is empty or text."""
    values = [cells[j] for j in js]
    return (
        [v for v in values if isinstance(v, int)]
        if all(isinstance(v, int) for v in values)
        else None
    )


def _at(letter: Letter, j: int, i: int) -> str:
    return f"{letter(j)}{i + FIRST_ROW}"
