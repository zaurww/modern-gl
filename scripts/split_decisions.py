"""Split the old decision log (one Markdown table) into one ADR file per decision.

    uv run python scripts/split_decisions.py <old DECISIONS.md> [docs/decisions]

One-off (the table became `docs/decisions/` in session 2026-10-27), kept so the move can be
checked: the script prints the number of characters in the table cells and in the written
files, and every cell lands verbatim in its file (the text under «Решение», the date under
«Дата»). The «Ещё не решено» list of the old file goes to `OPEN.md`. The index is made
separately by `scripts/decisions_index.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROW = re.compile(r"^\| (D\d+) \| (.*) \|$")
DATE = re.compile(r"^(.*) \| (\d{4}-\d{2}-\d{2})$")
REPLACED = re.compile(r"^~~(.*?)~~ — заменено решением (D\d+)\.")
BOLD = re.compile(r"\*\*(.+?)\*\*")
CODE = re.compile(r"`([^`]+)`")
CODE_LIKE = re.compile(r"/|\.py\b|\.sql\b|\.csv\b|^tests?/|^test_|^scripts/|^migrations?\b")
BRANCH = re.compile(r"^claude/")
OPEN_HEADING = "## Ещё не решено"

# File names: latin, 2–4 words by the meaning of the title; the number is zero-padded so
# `ls docs/decisions` sorts by number.
SLUGS = {
    1: "posting-debit-credit-pair",
    2: "subconto-in-core",
    3: "money-integer-kopecks",
    4: "one-sqlite-file",
    5: "red-storno-correction",
    6: "expanded-balance",
    7: "layer-vs-book",
    8: "no-1c-export",
    9: "plain-sqlite-migrations",
    10: "document-number-sequence",
    11: "chart-template-1c77",
    12: "interface-az-ru",
    13: "zeros-hidden-in-reports",
    14: "account-class",
    15: "chart-editing",
    16: "banks-as-subconto",
    17: "account-kind-removed",
    18: "file-per-company",
    19: "corrections-with-audit",
    20: "directories-section",
    21: "chart-template-classic",
    22: "account-code-optional",
    23: "operation-templates-formulas",
    24: "python-pyside-sqlite-stack",
    25: "target-user-consultant",
    26: "inventory-register",
    27: "stock-document-lifecycle",
    28: "currency-account-modes",
    29: "contracts-belong-counterparty",
    30: "tool-for-self",
    31: "regulated-reporting-separate",
    32: "posted-document-edit-in-place",
    33: "landed-cost-voucher",
    34: "account-roles",
    35: "account-type",
    36: "counterparty-tax-id",
    37: "currency-conversion-document",
    38: "eqaime-number-in-posting",
    39: "opening-balances-document",
    40: "opening-balances-table",
    41: "vat-deposit-account-type",
    42: "sale-document",
    43: "purchase-services-assets",
    44: "trade-section",
    45: "eqaime-import-drafts",
    46: "purchase-sale-sections",
    47: "bank-module",
    48: "save-company-as",
    49: "keyboard-before-mouse",
    50: "contract-optional",
    51: "eqaime-from-unpaid-list",
    52: "reports-jon-moon",
    53: "eqaime-pending-reconciliation",
    54: "enter-as-tab-cells",
    55: "same-entry-everywhere",
    56: "sidebar-sections",
    57: "portal-period-buttons",
    58: "non-stock-line-expense",
    59: "delete-mistaken-account-item",
    60: "directory-groups",
    61: "sales-analytics-subconto",
    62: "bank-commission-account",
    63: "parallel-books-per-company",
    64: "directory-item-tags",
    65: "late-eqaime-expense-76h",
    66: "bank-operation-form-column",
    67: "eqaime-payment-any-document",
    68: "bank-form-cursor-path",
    69: "vat-deposit-two-operations",
    70: "module-one-task",
    71: "modularity-scalability",
    72: "data-db-dev-practices",
    73: "document-status-not-checkbox",
    74: "full-db-check-on-backup",
    75: "document-owners-view",
    76: "purchase-expense-account-last",
    77: "db-engine-infrastructure-only",
    78: "bank-statements-by-day",
    79: "hledger-plaintext-export",
    80: "read-only-snapshot",
    81: "handover-zip",
    82: "who-entered-who-posted",
    83: "ai-assistant-mcp",
    84: "ai-drafts-only",
    85: "landed-cost-report",
    86: "design-system-things",
    87: "post-drafts-missing-accounts",
    88: "inventory-standalone-module",
    89: "current-vs-noncurrent-by-type",
    90: "stock-only-mode",
    91: "medaxil-receipt-reason",
    92: "d86-finished-theme-undo",
    93: "code-debt-modules-objects",
    94: "fast-entry-credit-amount",
    95: "period-closing-window",
    96: "change-reason-audit",
    97: "backups-visible-second-folder",
    98: "compare-books",
    99: "financial-statements-by-type",
    100: "cash-flow-direct-method",
    101: "module-rebuild-postings",
    102: "pnl-expense-where-arises",
    103: "table-zebra-optional",
    104: "excel-flat-report",
    105: "period-single-field",
    106: "comfort-rule",
    107: "report-columns-periods",
    108: "pnl-no-repeats-cost-46",
    109: "short-documents",
    110: "detail-like-1c-second-account",
    111: "team-and-sale-later",
    112: "vat-deposit-from-portal",
    113: "company-tax-id-check",
    114: "all-reports-hub",
    115: "vat-deposit-period-repeat",
    116: "report-columns-user-choice",
    117: "vat-deposit-preview",
    118: "vat-deposit-reconciliation",
    119: "purchase-awaiting-eqaime",
    120: "eqaime-postings-rule",
    121: "inventory-check-first",
    122: "layers-downwards-readme",
    123: "module-whole-package",
    124: "orders-subconto-projects",
    125: "subconto-analysis",
    126: "subconto-card",
    127: "report-design-concept",
    128: "pnl-ifrs18-deferred-tax",
    129: "period-capsule-calendar",
    130: "developer-api-exchange",
    131: "parallel-sessions-worktrees",
    132: "bank-one-click-navigation",
    133: "three-table-kinds",
    134: "two-books-tax-ifrs",
    135: "how-to-decide-disputed",
    136: "expense-period-purchase-line",
    137: "eqaime-goods-group-code",
    138: "vat-module-rules-by-year",
    139: "eqaime-register-report",
    140: "eqaime-correction-period",
    141: "register-reconciled-mark",
    142: "vat-sales-per-receipt",
    143: "receipts-eqaime-reconciliation",
    144: "supplier-payments-reconciliation",
    145: "vat-to-supplier-flag",
    146: "bank-statement-file-templates",
    147: "design-test-new-view",
    148: "company-file-upgrade-atomic",
    149: "file-holds-accounting-rules",
    150: "inventory-reports",
    151: "inventory-entry-party-stock-count",
    152: "document-language-company",
}


def parse_rows(text: str) -> list[tuple[int, str, str]]:
    """(number, cell text, date or '') for every `| Dn | … | date |` row of the table."""
    rows = []
    for line in text.splitlines():
        match = ROW.match(line)
        if not match:
            continue
        body, date = match[2], ""
        dated = DATE.match(body)
        if dated:
            body, date = dated[1], dated[2]
        rows.append((int(match[1][1:]), body, date))
    return rows


def title_and_status(body: str) -> tuple[str, str]:
    """The heading of a decision and its status, read from the cell text."""
    status = "принято"
    replaced = REPLACED.match(body)
    if replaced:
        status = f"заменено {replaced[2]}"
        body = body[replaced.end() :]
    bold = BOLD.search(body)
    title = bold[1] if bold else re.split(r"[.,]", body, maxsplit=1)[0]
    return title.strip().rstrip(".").strip(), status


def consequences(body: str) -> str:
    """Where the decision lives in the code: the code-like `…` references of the cell."""
    seen: list[str] = []
    for token in CODE.findall(body):
        if CODE_LIKE.search(token) and not BRANCH.match(token) and token not in seen:
            seen.append(token)
    return "Код: " + ", ".join(f"`{t}`" for t in seen) + "." if seen else "—"


def render(number: int, body: str, date: str) -> str:
    title, status = title_and_status(body)
    return (
        f"# D{number} — {title}\n"
        f"Статус: {status}\n"
        f"Дата: {date or '—'}\n\n"
        "## Контекст\n—\n\n"
        f"## Решение\n{body}\n\n"
        f"## Последствия\n{consequences(body)}\n"
    )


def open_questions(text: str) -> str:
    """The «Ещё не решено» list at the end of the old file, as it stands."""
    if OPEN_HEADING not in text:
        return ""
    tail = text[text.index(OPEN_HEADING) + len(OPEN_HEADING) :].strip("\n")
    return f"# Ещё не решено\n\nПеренесено из `docs/DECISIONS.md` как было.\n\n{tail}\n"


def main(argv: list[str]) -> None:
    source = Path(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else Path("docs/decisions")
    out.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    rows = parse_rows(text)
    before = after = 0
    for number, body, date in rows:
        page = render(number, body, date)
        (out / f"D{number:03d}-{SLUGS[number]}.md").write_text(page, encoding="utf-8")
        before += len(body) + len(date)
        after += len(page)
    questions = open_questions(text)
    if questions:
        (out / "OPEN.md").write_text(questions, encoding="utf-8")
    print(f"{len(rows)} decisions: {before} characters in cells, {after} in files")


if __name__ == "__main__":
    main(sys.argv)
