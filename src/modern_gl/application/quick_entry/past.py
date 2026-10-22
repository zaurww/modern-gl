"""«As the last time»: a word of a counterparty, a cost item or a memo brings back a
whole posting typed before, its amount ready to be typed over (like hledger add or
Quicken's QuickFill)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from fractions import Fraction

from modern_gl.application.catalog import Catalog
from modern_gl.application.queries import PastPosting
from modern_gl.application.quick_entry.parser import parse
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold

MOST = 5  # postings offered at once


def past_lines(
    typed: str, catalog: Catalog, history: Sequence[PastPosting]
) -> list[tuple[str, str, tuple[int, int]]]:
    """(label, line, span of the amount in the line) of the latest postings whose
    names or memo hold every typed word at the start of a word."""
    needles = fold(typed).split()
    if not needles or not any(c.isalpha() for c in typed):
        return []
    found = []
    for past in history:
        words = fold(" ".join(_names(past, catalog))).split()
        if not all(any(w.startswith(n) for w in words) for n in needles):
            continue
        written = _line(past, catalog)
        if written is None:
            continue
        line, span = written
        label = f"{line[: span[0]].rstrip()}   ·   {format_minor(_shown(past))}"
        if past.memo:
            label += f"   ·   {past.memo}"
        found.append((label, line, span))
        if len(found) == MOST:
            break
    return found


def _names(past: PastPosting, catalog: Catalog) -> list[str]:
    values = [catalog.value(v).name for v in (*past.debit_sc, *past.credit_sc) if v]
    accounts = [catalog.accounts[a].name for a in (past.debit, past.credit)]
    return [*values, *accounts, past.memo]


def _shown(past: PastPosting) -> int:
    return past.amount if past.currency_amount is None else past.currency_amount


def _number(minor: int) -> str:
    """As the line takes it: no spaces, a comma for kopecks."""
    whole, kopecks = divmod(minor, 100)
    return f"{whole},{kopecks:02d}" if kopecks else str(whole)


def _line(past: PastPosting, catalog: Catalog) -> tuple[str, tuple[int, int]] | None:
    """The posting as a line, or None when it does not read back the same (a name with
    "/" or ",", a subconto left empty before a filled one, an account without a code)."""

    def side(account: int, values: tuple[int | None, ...]) -> str:
        names = [catalog.value(v).name for v in values if v is not None]
        return " ".join([catalog.accounts[account].short, ", ".join(names)]).rstrip()

    head = f"{side(past.debit, past.debit_sc)} / {side(past.credit, past.credit_sc)} "
    amount = _number(_shown(past))
    tail = ""
    if past.currency_id is not None:
        tail += f" {catalog.currencies[past.currency_id].code}"
    if past.memo:
        tail += f" {past.memo}"
    line = head + amount + tail
    try:
        [ln] = parse(line, catalog, (), lambda _c, _d: Fraction(1), date.today()).lines
    except (LedgerError, ValueError):
        return None
    same = (ln.debit, tuple(ln.debit_sc), ln.credit, tuple(ln.credit_sc)) == (
        past.debit,
        tuple(past.debit_sc),
        past.credit,
        tuple(past.credit_sc),
    )
    if not same or ln.memo != past.memo:
        return None
    return line, (len(head), len(head) + len(amount))
