"""Quick entry: a document typed as one line of text (see quick_entry.parser)."""

from __future__ import annotations

from modern_gl.application.quick_entry.parser import (
    DATE,
    NEW,
    NewValue,
    QuickEntry,
    QuickLine,
    describe,
    parse,
)
from modern_gl.application.quick_entry.saving import posting_input, save_quick_entry
from modern_gl.application.quick_entry.suggest import (
    Suggestion,
    Suggestions,
    suggest,
)

__all__ = [
    "DATE",
    "NEW",
    "NewValue",
    "QuickEntry",
    "QuickLine",
    "Suggestion",
    "Suggestions",
    "describe",
    "parse",
    "posting_input",
    "save_quick_entry",
    "suggest",
]
