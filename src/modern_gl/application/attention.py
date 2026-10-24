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
_SOURCES: list[AttentionSource] = []


def attention_source(source: AttentionSource) -> AttentionSource:
    """A module's rows of «Требует внимания»: (conn, company_id, ISO day) → rows."""
    if source not in _SOURCES:
        _SOURCES.append(source)
    return source


def attention_sources() -> tuple[AttentionSource, ...]:
    """Every module's source, in the order the modules were loaded."""
    return tuple(_SOURCES)
