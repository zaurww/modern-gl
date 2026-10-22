"""Postings typed before, found by words of their names or memo: the quick entry line
offers them while typing and reads a line without "/" by them ("альфа аренда 450")."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from modern_gl.application.catalog import Catalog
from modern_gl.application.queries import PastPosting
from modern_gl.i18n import fold


def matching(
    words: Sequence[str], catalog: Catalog, history: Sequence[PastPosting]
) -> Iterator[PastPosting]:
    """The postings, newest first, whose names or memo hold every word at the start of
    one of their words; nothing when no word has a letter (account codes, amounts)."""
    needles = [fold(w) for w in words]
    if not needles or not any(c.isalpha() for w in words for c in w):
        return
    for past in history:
        haystack = fold(" ".join(_names(past, catalog))).split()
        if all(any(w.startswith(n) for w in haystack) for n in needles):
            yield past


def _names(past: PastPosting, catalog: Catalog) -> list[str]:
    values = [catalog.value(v).name for v in (*past.debit_sc, *past.credit_sc) if v]
    accounts = [catalog.accounts[a].name for a in (past.debit, past.credit)]
    return [*values, *accounts, past.memo]
