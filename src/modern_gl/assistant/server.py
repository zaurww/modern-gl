"""The assistant server: uv run modern-gl-mcp [--data FOLDER] [--file X.gl …] [--lang az|ru]
    [--allow-drafts]

An MCP server over stdio (D83) for Claude Desktop or any MCP client; it reads the company
files the program knows (its folder and remembered files), each as a read-only snapshot.
Claude Desktop, claude_desktop_config.json:
    "mcpServers": {"modern-gl": {"command": "uv",
        "args": ["--directory", "D:\\\\GL AZE", "run", "--no-sync", "modern-gl-mcp"]}}
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from modern_gl import i18n
from modern_gl.application.workspace import Workspace
from modern_gl.assistant import answers
from modern_gl.assistant.companies import Companies
from modern_gl.assistant.draft_tools import ABOUT as DRAFTS_ABOUT
from modern_gl.assistant.draft_tools import draft_tools
from modern_gl.assistant.drafts import Drafts
from modern_gl.assistant.protocol import Server, Session, Tool
from modern_gl.infrastructure.app_settings import default_folder, read_settings

ABOUT = """Modern GL — the user's accounting books (general ledger, 1C 7.7 style: postings
debit/credit with subconto — counterparties, contracts, bank accounts, items).
Reading never changes the books. Amounts are manat strings ("1234.50"); account
codes as in the chart (60 suppliers, 62 customers, 51 bank…). An ODV/VAT invoice is an
"e-qaimə". Check figures with the reports, quote document numbers, and when something looks
wrong, show the postings that prove it. Answer in the user's language."""

COMPANY = {
    "type": "string",
    "description": "company name (or its beginning); may be omitted when there is one",
}
DATE_FROM = {"type": "string", "description": "period start, YYYY-MM-DD"}
DATE_TO = {"type": "string", "description": "period end, YYYY-MM-DD"}
ACCOUNT = {
    "type": "string",
    "description": "account code, e.g. 60 or 68.2 (a group takes its subaccounts)",
}
BOOK = {
    "type": "string",
    "enum": list(answers.BOOKS),
    "description": "common (default), ifrs or tax — only if the company keeps parallel books",
}
PERIOD = {"company": COMPANY, "date_from": DATE_FROM, "date_to": DATE_TO}


def build_tools(companies: Companies, drafts: Drafts | None = None) -> list[Tool]:
    def opened(answer: Callable[..., dict]) -> Callable[..., dict]:
        def run(company: str = "", **arguments) -> dict:
            conn, company_id = companies.open(company)
            return answer(conn, company_id, **arguments)

        return run

    def company_list() -> dict:
        return {"companies": [f.name for f in companies.files()]}

    return [
        Tool("companies", "The companies (one file each) whose books can be read.", company_list),
        *_report_tools(opened),
        *_book_tools(opened),
        *(draft_tools(drafts) if drafts else []),
    ]


Opened = Callable[[Callable[..., dict]], Callable[..., dict]]


def _report_tools(opened: Opened) -> list[Tool]:
    return [
        Tool(
            "chart_of_accounts",
            "Chart of accounts: code, name, class, type, term (current / long_term for "
            "assets and liabilities), subconto directories; and the list of directories.",
            opened(answers.chart_of_accounts),
            {"company": COMPANY},
        ),
        Tool(
            "trial_balance",
            "Trial balance (ОСВ / dövriyyə cədvəli) for a period: opening, turnover, closing "
            "debit/credit per account; wrong_side marks a balance on the unexpected side.",
            opened(answers.trial_balance),
            {**PERIOD, "book": BOOK},
            ("date_from", "date_to"),
        ),
        Tool(
            "account_card",
            "Account card: every posting of the account in the period with its document, "
            "corresponding account and running balance.",
            opened(answers.account_card),
            {**PERIOD, "account": ACCOUNT, "book": BOOK},
            ("account", "date_from", "date_to"),
        ),
        Tool(
            "account_analysis",
            "Account analysis: the period's turnovers of an account by corresponding account.",
            opened(answers.account_analysis),
            {**PERIOD, "account": ACCOUNT, "book": BOOK},
            ("account", "date_from", "date_to"),
        ),
        Tool(
            "subconto_balance",
            "Balances of one account split by a subconto (e.g. 60 by counterparty).",
            opened(answers.subconto_balance),
            {
                **PERIOD,
                "account": ACCOUNT,
                "position": {"type": "integer", "enum": [1, 2, 3], "description": "default 1"},
                "book": BOOK,
            },
            ("account", "date_from", "date_to"),
        ),
    ]


def _book_tools(opened: Opened) -> list[Tool]:
    return [
        Tool(
            "documents",
            "Journal: documents dated in the period, with number, memo, status and total. "
            "`search` matches the memo or the number.",
            opened(answers.documents),
            {
                **PERIOD,
                "search": {"type": "string"},
                "drafts_only": {"type": "boolean"},
            },
            ("date_from", "date_to"),
        ),
        Tool(
            "document",
            "One document by its number: every posting with accounts, subconto, amount, "
            "currency and e-qaimə.",
            opened(answers.document),
            {"company": COMPANY, "number": {"type": "integer"}},
            ("number",),
        ),
        Tool(
            "directory",
            "Elements of a directory (counterparties with VÖEN, contracts, bank accounts, "
            "items…), optionally those matching `search` (name or VÖEN).",
            opened(answers.directory),
            {
                "company": COMPANY,
                "name": {"type": "string", "description": "directory name or code"},
                "search": {"type": "string"},
            },
            ("name",),
        ),
        Tool(
            "e_qaime",
            "E-qaimə (VAT invoices) by number: counterparty, settlement turnovers, VAT, unpaid "
            "balance and documents; `unpaid_only` — all with a balance, whatever the period.",
            opened(answers.e_qaime),
            {**PERIOD, "unpaid_only": {"type": "boolean"}},
            ("date_from", "date_to"),
        ),
    ]


def workspace_from(args: argparse.Namespace) -> Workspace:
    settings = read_settings()
    folder = args.data or settings.data_dir or default_folder()
    return Workspace(folder, [*settings.company_files, *args.file])


def main() -> None:
    parser = argparse.ArgumentParser(description="Modern GL: the books for an AI over MCP")
    parser.add_argument("--data", type=Path, help="folder of company files")
    parser.add_argument("--file", type=Path, action="append", default=[], help="a company file")
    parser.add_argument("--lang", choices=sorted(i18n.LANGUAGES))
    parser.add_argument(
        "--allow-drafts", action="store_true", help="let the AI prepare drafts (D84)"
    )
    args = parser.parse_args()
    language = args.lang or read_settings().language
    i18n.set_language(language if language in i18n.LANGUAGES else i18n.DEFAULT)
    companies = Companies(workspace_from(args))
    session = Session()
    drafts = Drafts(companies, lambda: session.client) if args.allow_drafts else None
    about = ABOUT + (DRAFTS_ABOUT if drafts else "")
    server = Server("modern-gl", "0.1.0", build_tools(companies, drafts), about, session)
    try:
        server.serve(sys.stdin.buffer, sys.stdout.buffer)
    finally:
        companies.close()


if __name__ == "__main__":
    main()
