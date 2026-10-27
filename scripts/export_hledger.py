"""Export a company's postings as an hledger journal (D79).

    uv run python scripts/export_hledger.py <company.gl> [-o out.journal]
        [--book common|ifrs|tax] [--to YYYY-MM-DD] [--lang az|ru]

Then, for example: hledger -f out.journal bs / is / bal / reg 531
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from modern_gl.application.books import COMMON, IFRS, TAX
from modern_gl.i18n import set_language
from modern_gl.infrastructure.company_file import open_company
from modern_gl.reporting.plaintext import hledger_journal

BOOKS = {"common": COMMON, "ifrs": IFRS, "tax": TAX}


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("company", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--book", choices=BOOKS, default="common")
    parser.add_argument("--to", default=date.today().isoformat())
    parser.add_argument("--lang", choices=("az", "ru"), default="az")
    args = parser.parse_args()
    set_language(args.lang)
    conn, company_id = open_company(args.company)
    try:
        text = hledger_journal(conn, company_id, args.to, BOOKS[args.book], date.today())
    finally:
        conn.close()
    output = args.output or args.company.with_suffix(f".{args.book}.journal")
    output.write_text(text, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
