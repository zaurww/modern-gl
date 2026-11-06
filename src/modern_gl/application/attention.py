"""«Требует внимания» (D86): what waits for the accountant, as rows of «Bu gün».

The core knows its own rows (the journal's drafts); a module adds the rows of what
waits in it with `attention_source` (D71) — the core never asks a module. The page's
reading of the rows is `reporting/overview.py`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from modern_gl.infrastructure.db import Connection

POST_DRAFTS = "post_drafts"  # the row's button: post them all


@dataclass(frozen=True)
class Attention:
    """One thing that waits: «Черновики в журнале · 3» → its place in the sidebar."""

    text: str
    count: int
    place: tuple[str, ...]
    amount: int | None = None  # in kopecks, when a sum tells more than the count
    action: str = ""  # POST_DRAFTS: a button on the row


AttentionSource = Callable[[Connection, int, str], list[Attention]]
_SOURCES: dict[AttentionSource, int] = {}

# where each module's rows stand on «Bu gün»: money first, then goods, then papers —
# an explicit place, not the order in which the modules happened to be imported
BANK, BELOW_MINIMUM, STOCK, WAITING_EXPENSES = 10, 15, 20, 25
UNPAID_INVOICES, AWAITING_INVOICES = 30, 40


def attention_source(place: int) -> Callable[[AttentionSource], AttentionSource]:
    """A module's rows of «Требует внимания»: (conn, company_id, ISO day) → rows, shown
    at `place` among the modules' rows (the constants above)."""

    def register(source: AttentionSource) -> AttentionSource:
        _SOURCES[source] = place
        return source

    return register


def attention_sources() -> tuple[AttentionSource, ...]:
    """Every loaded module's source, by its place."""
    return tuple(sorted(_SOURCES, key=lambda source: _SOURCES[source]))
