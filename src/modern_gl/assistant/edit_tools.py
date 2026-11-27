"""The assistant's tools that change what is posted, offered when the server is started
with --allow-edits."""

from __future__ import annotations

from modern_gl.assistant.draft_tools import COMPANY, DOCUMENT
from modern_gl.assistant.edits import Edits
from modern_gl.assistant.protocol import Tool

ABOUT = """
You may also CORRECT documents the user points at: change_document, set_e_qaime,
unpost_document. Rules: (1) change only what the user asked to correct, one document a
call; never sweep many documents on your own finding — list them and ask. (2) Before a
change, read the document and tell the user what it is and what it will become; after it,
show before and after. (3) Two alike documents are not always a duplicate (two real
payments of a day): ask when in doubt. (4) A duplicate is unposted, never deleted — the
user deletes the draft. (5) Always give `reason` in the user's language: it stays in the
document's history. (6) A closed period and documents of the warehouse or the currency
conversion are not yours to change: say so. You never post a draft."""

NUMBER = {"type": "integer", "description": "the document's number"}
REASON = {
    "type": "string",
    "description": "why, in the user's language — kept in the document's history",
}


def edit_tools(edits: Edits) -> list[Tool]:
    return [
        Tool(
            "change_document",
            "Replace a JOURNAL document (by number) whole: date, memo and all postings. A "
            "posted one stays posted, in place, keeping its number (open period only). Not "
            "for documents a module made (bank, warehouse). Returns before and after.",
            edits.change_document,
            {**DOCUMENT, "number": NUMBER, "reason": REASON},
            ("number", "date", "memo", "postings", "reason"),
            writes=True,
            destructive=True,
        ),
        Tool(
            "set_e_qaime",
            "Change only the e-qaimə number in a document's lines: every line with `old` "
            "gets `new` (empty `old` — the one line without a number; empty `new` — take "
            "the number off). Journal documents and bank operations. Returns before, after.",
            edits.set_e_qaime,
            {
                "company": COMPANY,
                "number": NUMBER,
                "old": {"type": "string", "description": "the number the lines carry now"},
                "new": {"type": "string", "description": "the right number"},
                "reason": REASON,
            },
            ("number", "old", "new", "reason"),
            writes=True,
            destructive=True,
        ),
        Tool(
            "unpost_document",
            "Take a posted document (journal or bank operation) out of the books: it becomes "
            "a draft, nothing is deleted — for a duplicate. Open period only.",
            edits.unpost_document,
            {"company": COMPANY, "number": NUMBER, "reason": REASON},
            ("number", "reason"),
            writes=True,
            destructive=True,
        ),
    ]
