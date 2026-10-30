"""The rows of the trial balance as a tree the user opens by place (D-new-interactive-osv):
an account, under it what the user split it by — a subconto, the corresponding accounts,
the months — and under any of those rows another split. What is opened and what was
read for it is the `OsvTree`; `assemble` lays the rows out for the table, sorted as the
user asked. The figures come from `reporting.reports.osv_expand`."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.desktop.reports_page.table import INDENT
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.reports import (
    CORR,
    MONTH,
    SUBCONTO_KINDS,
    ExpandRow,
    Osv,
    OsvRow,
    Step,
    SubcontoRow,
    expand_many,
)

# an account and the steps that name a row under it; () — the account's own row
NodeKey = tuple[int, tuple[Step, ...]]


@dataclass
class ExpandedRow(OsvRow):
    """A row of a split under an account: named by its steps, the last of them its own."""

    steps: tuple[Step, ...] = ()
    kind: str = ""

    @property
    def key(self) -> NodeKey:
        return (self.account_id, self.steps)


def node_of(row: Any) -> NodeKey | None:
    """What a row of the table is in the tree; None — not a row that can be split."""
    if isinstance(row, ExpandedRow):
        return row.key
    if isinstance(row, OsvRow) and row.account_id and type(row) is OsvRow and row.depth >= 0:
        return (row.account_id, ())
    return None


class OsvTree:
    """What the user opened under the accounts, and the rows read for it."""

    def __init__(self) -> None:
        self.opened: dict[NodeKey, str] = {}  # node -> the kind it is split by
        self.read: dict[NodeKey, list[ExpandRow]] = {}

    def open(self, key: NodeKey, by: str) -> None:
        self.close(key)
        self.opened[key] = by

    def close(self, key: NodeKey) -> None:
        """The node and everything under it."""
        account, steps = key
        under = [k for k in self.opened if k[0] == account and k[1][: len(steps)] == steps]
        for k in under:
            del self.opened[k]
            self.read.pop(k, None)

    def clear(self) -> None:
        self.opened.clear()
        self.read.clear()

    def forget(self) -> None:
        """What was read is stale (another period): read again, the same nodes open."""
        self.read.clear()

    def missing(self) -> dict[NodeKey, str]:
        return {k: by for k, by in self.opened.items() if k not in self.read}

    def read_missing(self, conn: Connection, company_id: int, params: Any) -> None:
        """Read the rows of the opened nodes not read yet — nodes alike in one query."""
        read_nodes(conn, company_id, params, self.missing(), self.read)

    def to_list(self) -> list[list[Any]]:
        """For a saved view: [[account id, [[kind, value]…], kind]…]."""
        return [[a, [list(s) for s in steps], by] for (a, steps), by in self.opened.items()]

    def from_list(self, items: Iterable[Any]) -> None:
        self.clear()
        for account, steps, by in items:
            self.opened[(int(account), tuple((k, v) for k, v in steps))] = str(by)


def read_nodes(
    conn: Connection,
    company_id: int,
    params: Any,
    wanted: dict[NodeKey, str],
    into: dict[NodeKey, list[ExpandRow]],
) -> None:
    """The rows of `wanted` nodes into `into`: the nodes with the same steps and kind
    (every account split by its counterparties) go in one query."""
    alike: dict[tuple[tuple[Step, ...], str], list[int]] = defaultdict(list)
    for (account, steps), by in wanted.items():
        alike[(steps, by)].append(account)
    for (steps, by), accounts in alike.items():
        found = expand_many(
            conn, company_id, accounts, params.date_from, params.date_to, params.layers, steps, by
        )
        for account in accounts:
            into[(account, steps)] = found[account]


# ---- what a row can be split by ----------------------------------------------------


def kinds_of(
    acc: AccountInfo, steps: tuple[Step, ...], months: int, cat: Catalog
) -> list[tuple[str, str]]:
    """(kind, its name) a row may be split by: the subconto positions not used yet, the
    corr accounts once, the months when the period has more than one."""
    used = {kind for kind, _ in steps}
    kinds: list[tuple[str, str]] = []
    for position, kind_id in zip(SUBCONTO_KINDS, acc.sc_kinds, strict=True):
        if kind_id is not None and position not in used:
            kinds.append((position, cat.kinds.get(kind_id, position)))
    if CORR not in used:
        kinds.append((CORR, tr("Корсчета")))
    if MONTH not in used and months > 1:
        kinds.append((MONTH, tr("По месяцам")))
    return kinds


def natural_kind(
    acc: AccountInfo, steps: tuple[Step, ...], months: int, cat: Catalog
) -> str | None:
    """What → opens a row by: the next subconto, else the corr accounts, else the months."""
    kinds = kinds_of(acc, steps, months, cat)
    return kinds[0][0] if kinds else None


# ---- the rows for the table ---------------------------------------------------------


@dataclass
class Layout:
    """How the rows are laid out: the whole subconto tree under every account (the
    «Субконто» view), and the order within siblings."""

    subconto: bool = False
    sort_value: Callable[[Any], Any] | None = None
    descending: bool = False


def assemble(osv: Osv, shown: list[OsvRow], tree: OsvTree, layout: Layout) -> list[OsvRow]:
    """The account rows (`shown`, in chart order with their depth) with the rows under
    each: a node's split (what the user opened) or, in the «Субконто» view, its
    subconto tree; siblings sorted when a sort is on."""
    static = _static_children(osv) if layout.subconto else {}
    out: list[OsvRow] = []

    def emit(node: NodeKey, depth: int) -> None:
        kids = tree.read.get(node) if node in tree.opened else None
        if kids is not None:
            rows = [_expanded(node, kid, depth) for kid in kids]
        elif node in static:
            rows = [_from_subconto(node[0], s, depth) for s in static[node]]
        else:
            return
        for row in _ordered(rows, layout):
            out.append(row)
            emit(row.key, depth + 1)

    def emit_account(row: OsvRow, children: list[OsvRow]) -> None:
        out.append(row)
        emit((row.account_id, ()), row.depth + 1)
        for child in _ordered(children, layout):
            emit_account(child, _under(child, by_parent))

    by_parent = _account_children(shown)
    for top in _ordered(by_parent.get(None, []), layout):
        emit_account(top, _under(top, by_parent))
    return out


def _under(row: OsvRow, by_parent: dict[int | None, list[OsvRow]]) -> list[OsvRow]:
    return by_parent.get(row.account_id, [])


def _account_children(rows: list[OsvRow]) -> dict[int | None, list[OsvRow]]:
    """parent account -> its rows, from the flat list in chart order with depths."""
    children: dict[int | None, list[OsvRow]] = defaultdict(list)
    stack: list[OsvRow] = []
    for r in rows:
        while stack and stack[-1].depth >= r.depth:
            stack.pop()
        children[stack[-1].account_id if stack else None].append(r)
        stack.append(r)
    return children


def _static_children(osv: Osv) -> dict[NodeKey, list[SubcontoRow]]:
    """The subconto tree of every account as children per node (D110)."""
    children: dict[NodeKey, list[SubcontoRow]] = defaultdict(list)
    for account, rows in osv.subconto.items():
        for s in rows:
            children[(account, _steps(s.path[:-1]))].append(s)
    return children


def _steps(path: tuple[int | None, ...]) -> tuple[Step, ...]:
    return tuple((SUBCONTO_KINDS[i], v) for i, v in enumerate(path))


def _from_subconto(account: int, s: SubcontoRow, depth: int) -> ExpandedRow:
    steps = _steps(s.path)
    row = ExpandedRow(
        account_id=account,
        name=INDENT * depth + s.name,
        depth=depth,
        subconto=s.path,
        steps=steps,
        kind=steps[-1][0],
    )
    row.add(s)
    return row


def _expanded(node: NodeKey, kid: ExpandRow, depth: int) -> ExpandedRow:
    account, steps = node
    own = (*steps, (kid.kind, kid.value))
    row = ExpandedRow(
        account_id=account,
        code=kid.code,
        name=INDENT * depth + kid.name,
        depth=depth,
        subconto=subconto_of(own),
        steps=own,
        kind=kid.kind,
    )
    row.add(kid)
    return row


def subconto_of(steps: tuple[Step, ...]) -> tuple[int | None, ...]:
    """The subconto values the steps name from the first position on, in order —
    what the card of the row is opened for; a gap or another kind ends them."""
    values: list[int | None] = []
    for position in SUBCONTO_KINDS:
        found = [v for k, v in steps if k == position]
        if not found:
            break
        values.append(found[0] if isinstance(found[0], int) else None)
    return tuple(values)


def months_of(steps: tuple[Step, ...]) -> str | None:
    """The month a row is narrowed to, if any."""
    return next((str(v) for k, v in steps if k == MONTH), None)


def _ordered[R: OsvRow](rows: list[R], layout: Layout) -> list[R]:
    value_of = layout.sort_value
    if value_of is None:
        return rows
    return sorted(rows, key=lambda r: _sort_key(value_of, r), reverse=layout.descending)


def _sort_key(value_of: Callable[[Any], Any], row: Any) -> Any:
    value = value_of(row)
    return value.strip().casefold() if isinstance(value, str) else (value or 0)
