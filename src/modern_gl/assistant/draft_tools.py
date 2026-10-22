"""The assistant's writing tools: drafts only, offered when the server is started with
--allow-drafts (D84)."""

from __future__ import annotations

from modern_gl.assistant.drafts import Drafts
from modern_gl.assistant.protocol import Tool

ABOUT = """
You may prepare DRAFT journal documents (create_draft); you never post — the user checks
each draft in the program and posts it. Use only accounts of the chart and elements that
exist in the directories (look them up first); if one is missing, tell the user to add it.
Every answer says would_post and, if not, the problem: fix the draft (update_draft)."""

LINE = {
    "type": "object",
    "properties": {
        "debit": {"type": "string", "description": "debit account code, e.g. 60"},
        "debit_subconto": {
            "type": "array",
            "items": {"type": "string"},
            "description": "elements in the order of the account's subconto: names or VÖEN",
        },
        "credit": {"type": "string", "description": "credit account code"},
        "credit_subconto": {"type": "array", "items": {"type": "string"}},
        "amount": {"type": "string", "description": 'manat, as text: "261.13"'},
        "memo": {"type": "string"},
        "e_qaime": {"type": "string", "description": "e-qaimə number, if the line has one"},
        "currency": {"type": "string", "description": "currency code, for currency accounts"},
        "currency_amount": {"type": "string", "description": "the amount in that currency"},
    },
    "required": ["debit", "credit", "amount"],
    "additionalProperties": False,
}
COMPANY = {"type": "string", "description": "company name; may be omitted when there is one"}
DOCUMENT = {
    "company": COMPANY,
    "date": {"type": "string", "description": "YYYY-MM-DD"},
    "memo": {"type": "string", "description": "what the document is about"},
    "postings": {"type": "array", "items": LINE, "minItems": 1},
}


def draft_tools(drafts: Drafts) -> list[Tool]:
    return [
        Tool(
            "create_draft",
            "Create a DRAFT journal document (debit/credit postings). Not posted: the user "
            "posts it. Returns the draft, would_post and the problem if it would not post.",
            drafts.create,
            DOCUMENT,
            ("date", "memo", "postings"),
            writes=True,
        ),
        Tool(
            "update_draft",
            "Replace a draft the assistant made (by number): date, memo and all postings.",
            drafts.update,
            {**DOCUMENT, "number": {"type": "integer"}},
            ("number", "date", "memo", "postings"),
            writes=True,
        ),
        Tool(
            "delete_draft",
            "Delete a draft the assistant made (by number).",
            drafts.delete,
            {"company": COMPANY, "number": {"type": "integer"}},
            ("number",),
            writes=True,
        ),
    ]
