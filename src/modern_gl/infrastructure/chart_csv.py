"""Import a chart of accounts from CSV (Excel 'CSV UTF-8', ';'-separated).

Columns: code;name;parent;group;subconto[;class;contra;two_sided;currency]
  code      - optional: an account without a code is known by its name
  parent    - parent account code, empty for top level (parents must come first)
  group     - 1 for a group (no postings allowed), empty or 0 otherwise
  subconto  - subconto kind codes for positions 1..3, comma-separated; must already exist
  class     - optional: asset / liability / equity / revenue / expense (empty: parent's)
  contra    - optional: 1 for a contra account (e.g. accumulated depreciation)
  two_sided - optional: 1 if the balance may be on either side (settlements, taxes)
  currency  - optional: 1 if every posting is in a currency (52), 2 if postings may be in
              manat or in a currency (60, 62: local and foreign partners)

A 1C-style `kind` column (A / P / AP) is also understood: AP means two-sided,
and A / P give the class (asset / liability) when `class` is empty.
"""

from __future__ import annotations

import csv
from pathlib import Path

from modern_gl.application.ledger import Ledger, TemplateLine
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import language, tr
from modern_gl.infrastructure.db import transaction

COLUMNS = ("code", "name", "parent", "group", "subconto")
SUBCONTO_COLUMNS = ("code", "name")
ENTRY_COLUMNS = ("template", "debit", "credit", "formula", "memo")
TEMPLATES_DIR = Path(__file__).parent / "templates"
LEGACY_CLASS = {"A": "asset", "P": "liability"}
# Each template exists per language: chart_<name>_<lang>.csv, chart_<name>_subconto_<lang>.csv
# and, optionally, ready entry templates (типовые операции): entries_<name>_<lang>.csv
TEMPLATES = ("classic", "1c77")
DEFAULT_TEMPLATE = "classic"


def _read_rows(path: str | Path, columns: tuple[str, ...], delimiter: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        missing = set(columns) - set(reader.fieldnames or ())
        if missing:
            raise ValidationError(
                tr("{file}: нет колонок {cols}", file=Path(path).name, cols=sorted(missing))
            )
        return list(reader)


def apply_chart_template(
    ledger: Ledger, company_id: int, name: str = DEFAULT_TEMPLATE, lang: str | None = None
) -> int:
    """Create a template's subconto kinds and accounts in one transaction.

    "classic" is the short pre-2000 chart (46 sales, 80 profit and loss, ~37 accounts);
    "1c77" is the full 1C 7.7 chart on the 2000 plan (90 sales, subaccounts like 60.1).
    Names come in the given language (default: the interface language). Ready entry
    templates for the chart are added too, if it has them.
    """
    if name not in TEMPLATES:
        raise ValidationError(
            tr("нет шаблона {name}; есть: {names}", name=name, names=list(TEMPLATES))
        )
    lang = lang or language()
    with transaction(ledger.conn):
        kinds_file = TEMPLATES_DIR / f"chart_{name}_subconto_{lang}.csv"
        for row in _read_rows(kinds_file, SUBCONTO_COLUMNS, ";"):
            owner = (row.get("owner") or "").strip()  # contracts belong to counterparties
            ledger.add_subconto_kind(
                company_id,
                row["code"].strip(),
                row["name"].strip(),
                owner_kind_id=ledger.subconto_kind_id(company_id, owner) if owner else None,
            )
        count = import_chart_csv(ledger, company_id, TEMPLATES_DIR / f"chart_{name}_{lang}.csv")
        entries = TEMPLATES_DIR / f"entries_{name}_{lang}.csv"
        if entries.exists():
            import_entry_templates(ledger, company_id, entries)
        return count


def import_entry_templates(ledger: Ledger, company_id: int, path: str | Path) -> int:
    """Entry templates from CSV, one row per line: template;debit;credit;formula;memo.
    Lines of a template are consecutive rows with the same template name."""
    grouped: dict[str, list[TemplateLine]] = {}
    for row in _read_rows(path, ENTRY_COLUMNS, ";"):

        def account(code: str) -> int | None:
            return ledger.account_id(company_id, code.strip()) if code.strip() else None

        grouped.setdefault(row["template"].strip(), []).append(
            TemplateLine(
                account(row["debit"] or ""),
                account(row["credit"] or ""),
                (row["formula"] or "").strip(),
                memo=(row["memo"] or "").strip(),
            )
        )
    with transaction(ledger.conn):
        for name, lines in grouped.items():
            ledger.save_template(company_id, name, lines, memo=name)
    return len(grouped)


def import_chart_csv(
    ledger: Ledger, company_id: int, path: str | Path, delimiter: str = ";"
) -> int:
    """Import all accounts atomically; returns the number of accounts added."""
    rows = _read_rows(path, COLUMNS, delimiter)

    with transaction(ledger.conn):
        for line_no, row in enumerate(rows, start=2):
            try:
                kinds = [c.strip() for c in (row["subconto"] or "").split(",") if c.strip()]
                legacy = (row.get("kind") or "").strip().upper()
                account_class = (row.get("class") or "").strip().lower() or LEGACY_CLASS.get(legacy)
                two_sided = (row.get("two_sided") or "").strip() == "1" or legacy == "AP"
                if row.get("two_sided") is None and not legacy:
                    two_sided = None  # no such column: inherit from the parent
                ledger.add_account(
                    company_id,
                    row["code"].strip(),
                    row["name"].strip(),
                    parent=(row["parent"] or "").strip() or None,
                    is_group=(row["group"] or "").strip() == "1",
                    subconto=[ledger.subconto_kind_id(company_id, k) for k in kinds],
                    account_class=account_class,
                    contra=(row.get("contra") or "").strip() == "1",
                    two_sided=two_sided,
                    currency=None
                    if row.get("currency") is None
                    else int((row["currency"] or "").strip() or 0),
                )
            except Exception as e:
                raise ValidationError(
                    tr(
                        "{file}, строка {line}: {error}",
                        file=Path(path).name,
                        line=line_no,
                        error=e,
                    )
                ) from e
    return len(rows)
