"""The line as a card while it is typed (like Fantastical's event preview): each posting
with its sides, what is still missing in its place, the amount."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.catalog import Catalog
from modern_gl.application.quick_entry.parser import QuickEntry, QuickLine
from modern_gl.domain.currency import format_unit_rate
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


@dataclass(frozen=True)
class Part:
    text: str
    kind: str  # "account", "value", "new" (added when posted), "missing" (still empty)


@dataclass
class CardLine:
    debit: list[Part] = field(default_factory=list)
    credit: list[Part] = field(default_factory=list)
    amount: Part = Part("", "missing")
    in_manat: str = ""  # a currency line: "× 1.7000 = 170.00"
    memo: str = ""
    invoice: str = ""


def card(entry: QuickEntry, catalog: Catalog) -> list[CardLine]:
    lines = []
    for i, ln in enumerate(entry.lines):
        new = {
            (side, pos): v.name
            for v in entry.new_values
            for index, side, pos in v.cells
            if index == i
        }
        lines.append(
            CardLine(
                _side(catalog, ln.debit, ln.debit_sc, "debit", new),
                _side(catalog, ln.credit, ln.credit_sc, "credit", new),
                *_amount(catalog, ln),
                ln.memo if ln.memo != entry.memo else "",
                ln.invoice,
            )
        )
    return lines


def _side(
    catalog: Catalog,
    account: int | None,
    values: list[int | None],
    side: str,
    new: dict[tuple[str, int], str],
) -> list[Part]:
    if account is None:
        return [Part(tr("счёт"), "missing")]
    acc = catalog.accounts[account]
    parts = [Part(acc.short, "account")]
    for pos, kind in enumerate(acc.sc_kinds):
        if kind is None:
            continue
        if values[pos] is not None:
            parts.append(Part(catalog.value(values[pos]).name, "value"))  # type: ignore[arg-type]
        elif (side, pos) in new:
            parts.append(Part("+" + new[side, pos], "new"))
        elif pos not in acc.sc_optional:
            parts.append(Part(catalog.kinds[kind], "missing"))
    return parts


def _amount(catalog: Catalog, ln: QuickLine) -> tuple[Part, str]:
    if ln.amount is None:
        return Part(tr("сумма"), "missing"), ""
    if ln.currency_id is None or ln.currency_amount is None:
        return Part(format_minor(ln.amount), "amount"), ""
    code = catalog.currencies[ln.currency_id].code
    rate = format_unit_rate(ln.rate) if ln.rate is not None else "?"
    shown = Part(f"{format_minor(ln.currency_amount)} {code}", "amount")
    return shown, f"× {rate} = {format_minor(ln.amount)}"
