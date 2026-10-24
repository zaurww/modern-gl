"""`modern-gl-cli` — the API from a terminal or another program's script (D130): JSON
out on stdout, the exit code says whether it went through (0 yes, 1 a problem with the
data, 2 a wrong command). A company is a file path.

    modern-gl-cli trial-balance "Xəzər.gl" --from 2026-01-01 --to 2026-03-31
    modern-gl-cli export "Xəzər.gl" --from 2026-03-01 --to 2026-03-31 > march.json
    modern-gl-cli import "Başqa.gl" march.json --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modern_gl import i18n
from modern_gl.api import API_VERSION, LedgerError, open_company
from modern_gl.infrastructure.app_settings import read_settings


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    language = args.lang or read_settings().language
    i18n.set_language(language if language in i18n.LANGUAGES else i18n.DEFAULT)
    try:
        answer, ok = _run(args)
    except (LedgerError, LookupError, ValueError, OSError) as e:  # FormatError is a ValueError
        answer, ok = {"error": str(e)}, False
    json.dump(answer, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if ok else 1


def _run(args: argparse.Namespace) -> tuple[dict, bool]:
    if args.command == "import":
        data = json.loads(Path(args.documents).read_text(encoding="utf-8"))
        with open_company(args.company, write=True, actor=args.actor) as company:
            answer = company.import_documents(data, post=args.post, check=args.check)
        return answer, answer["ok"]
    with open_company(args.company) as company:
        if args.command == "chart":
            return company.chart_of_accounts(), True
        if args.command == "trial-balance":
            return company.trial_balance(args.date_from, args.date_to, args.book), True
        return company.export_documents(args.date_from, args.date_to, args.book), True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modern-gl-cli", description=f"Modern GL for developers, API {API_VERSION}"
    )
    parser.add_argument("--lang", choices=sorted(i18n.LANGUAGES), help="language of messages")
    commands = parser.add_subparsers(dest="command", required=True)
    chart = commands.add_parser("chart", help="chart of accounts")
    chart.add_argument("company", type=Path, help="company file (.gl)")
    for name, about in (
        ("trial-balance", "trial balance (ОСВ) of a period"),
        ("export", "posted documents of a period as an exchange file"),
    ):
        command = commands.add_parser(name, help=about)
        command.add_argument("company", type=Path, help="company file (.gl)")
        command.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
        command.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
        command.add_argument("--book", choices=("common", "ifrs", "tax"), default="common")
    load = commands.add_parser("import", help="documents from an exchange file")
    load.add_argument("company", type=Path, help="company file (.gl)")
    load.add_argument("documents", type=Path, help="exchange file (.json)")
    load.add_argument("--post", action="store_true", help="post them, not drafts")
    load.add_argument("--check", action="store_true", help="only say what would happen")
    load.add_argument("--actor", default="", help="who imports: shown as the author")
    return parser


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
