"""What the quick entry line offers while the user types: accounts, subconto, a new
element, currencies, templates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.catalog import AccountInfo, Catalog, search
from modern_gl.application.queries import TemplateData
from modern_gl.application.quick_entry.parser import NEW, token_date, token_number
from modern_gl.i18n import fold, tr


@dataclass(frozen=True)
class Suggestion:
    label: str  # shown in the list
    insert: str  # replaces the word being typed


@dataclass
class Suggestions:
    start: int  # where the word being typed starts; it is replaced up to the cursor
    items: list[Suggestion] = field(default_factory=list)
    typed: bool = False  # something is typed: the best match may be taken with Enter


def suggest(
    text: str,
    cursor: int,
    catalog: Catalog,
    templates: Sequence[TemplateData] = (),
    recent: Callable[[int, int], list[int]] = lambda _account, _position: [],
) -> Suggestions:
    """What fits where the cursor is: accounts, then the elements of their subconto in
    order (recently used on the account first; the contracts of the counterparty
    chosen), a currency after the amount, templates after "#". Choosing an element adds
    what comes next: ", " for the next subconto, " / " after the Dt side."""
    before = text[:cursor]
    seg_start = max(before.rfind(";"), before.rfind("\n")) + 1
    segment = before[seg_start:]
    lead = len(segment) - len(segment.lstrip())
    words = segment.split()
    date_done = len(words) > 1 or segment.rstrip() != segment  # "05.03 " — the date is typed
    if words and date_done and token_date(words[0], date.today()) is not None:
        lead = segment.index(words[0]) + len(words[0])
        lead += len(segment[lead:]) - len(segment[lead:].lstrip())
    body = segment[lead:]
    offset = seg_start + lead
    if body.startswith("#"):
        return _suggest_template(body, offset, templates)
    if "/" in body:
        slash = body.index("/")
        side_text, side_start, credit = body[slash + 1 :], offset + slash + 1, True
    else:
        side_text, side_start, credit = body, offset, False
    stripped = side_text.lstrip()
    side_start += len(side_text) - len(stripped)
    if not stripped or " " not in stripped:  # the account is being typed
        if not stripped and not credit:
            return Suggestions(side_start)
        items = [Suggestion(a.label, f"{a.short} ") for a in catalog.leaf_accounts]
        return _filter(items, stripped, side_start)
    word = stripped.split()[0]
    try:
        account = catalog.resolve_account(word)
    except LookupError:
        return Suggestions(cursor)
    rest_start = side_start + len(word)
    rest = before[rest_start:cursor]
    found = _suggest_subconto(catalog, account, rest, rest_start, credit, recent)
    if found.items or not credit:
        return found
    return _suggest_currency(catalog, account, rest, rest_start)


def _filter(items: list[Suggestion], typed: str, start: int) -> Suggestions:
    labels = search([i.label for i in items], typed)
    by_label = {i.label: i for i in items}
    return Suggestions(start, [by_label[label] for label in labels], bool(typed.strip()))


def _suggest_subconto(
    catalog: Catalog,
    account: AccountInfo,
    rest: str,
    rest_start: int,
    credit: bool,
    recent: Callable[[int, int], list[int]],
) -> Suggestions:
    slots = [(i, k) for i, k in enumerate(account.sc_kinds) if k is not None]
    pieces = rest.split(",")
    n = len(pieces) - 1  # the piece being typed
    if n >= len(slots) or (not rest.startswith(" ") and n == 0):
        return Suggestions(rest_start + len(rest))
    typed = pieces[-1].lstrip()
    start = rest_start + len(rest) - len(typed)
    values: list[int | None] = [None, None, None]
    for (pos, kind), piece in zip(slots, pieces[:-1], strict=False):
        with suppress(LookupError):  # a piece that names nothing yet: no owner from it
            values[pos] = catalog.resolve_value(kind, piece, catalog.owner_in(account, values, pos))
    pos, kind = slots[n]
    owner = catalog.owner_in(account, values, pos)
    last = n == len(slots) - 1
    tail = " " if credit and last else (" / " if last else ", ")
    offered = catalog.values(kind, owner)
    name = typed.strip()
    # on the Kt side the amount and the memo may follow any subconto: "Бета 400 Услуги"
    amount_typed = credit and any(token_number(w) for w in name.split()[1:])
    if typed.startswith(NEW):  # "+Name": only the new element, once the name is typed
        if not name[1:].strip() or amount_typed:
            return Suggestions(start)
        return Suggestions(start, _new_value(catalog.kinds[kind], name[1:], tail), True)
    first = [v for v in recent(account.id, pos + 1) if v in {o.id for o in offered}]
    ordered = [catalog.value(v) for v in first] + [v for v in offered if v.id not in first]
    items = [Suggestion(v.label, v.name + tail) for v in ordered]  # found by VÖEN too
    found = _filter(items, typed, start)
    known = any(fold(v.name) == fold(name) for v in offered)
    if (name or not offered) and not known and not amount_typed:
        found.items += _new_value(catalog.kinds[kind], name, tail)
    return found


def _new_value(kind: str, name: str, tail: str) -> list[Suggestion]:
    """Add an element right from the line: it is created when the document is posted."""
    name = name.strip()
    if not name:
        return [Suggestion(tr("+ Новый элемент «{kind}» — напишите название", kind=kind), NEW)]
    return [
        Suggestion(tr("+ Добавить «{name}» в «{kind}»", name=name, kind=kind), NEW + name + tail)
    ]


def _suggest_currency(
    catalog: Catalog, account: AccountInfo, rest: str, rest_start: int
) -> Suggestions:
    """After the amount on a currency account: "400 us" -> USD."""
    words = rest.split()
    if not account.currency or len(words) < 2 or not token_number(words[-2]) or rest.endswith(" "):
        return Suggestions(rest_start + len(rest))
    typed = words[-1]
    if len(typed) < 2 or not typed.isalpha():
        return Suggestions(rest_start + len(rest))
    start = rest_start + len(rest) - len(typed)
    items = [
        Suggestion(c.label, f"{c.code} ")
        for c in catalog.active_currencies
        if c.code.startswith(typed.upper())
    ]
    return Suggestions(start, items, True)


def _suggest_template(body: str, offset: int, templates: Sequence[TemplateData]) -> Suggestions:
    typed = body[1:]
    if any(token_number(w) for w in typed.split()):
        return Suggestions(offset + len(body))
    items = [Suggestion(f"#{t.name}", f"#{t.name} ") for t in templates]
    return _filter(items, body, offset)
