"""Import a chart of accounts from CSV (Excel 'CSV UTF-8', ';'-separated).

Columns: code;name;parent;group;subconto[;class;contra;two_sided]
  parent    - parent account code, empty for top level (parents must come first)
  group     - 1 for a group (no postings allowed), empty or 0 otherwise
  subconto  - subconto kind codes for positions 1..3, comma-separated; must already exist
  class     - optional: asset / liability / equity / revenue / expense (empty: parent's)
  contra    - optional: 1 for a contra account (e.g. accumulated depreciation)
  two_sided - optional: 1 if the balance may be on either side (settlements, taxes)

A 1C-style `kind` column (A / P / AP) is also understood: AP means two-sided,
and A / P give the class (asset / liability) when `class` is empty.
"""

from __future__ import annotations

import csv
from pathlib import Path

from modern_gl.application.ledger import Ledger
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import language, tr
from modern_gl.infrastructure.db import transaction

COLUMNS = ("code", "name", "parent", "group", "subconto")
SUBCONTO_COLUMNS = ("code", "name")
TEMPLATES_DIR = Path(__file__).parent / "templates"
LEGACY_CLASS = {"A": "asset", "P": "liability"}
# Each template exists per language: chart_<name>_<lang>.csv, chart_<name>_subconto_<lang>.csv
TEMPLATES = ("1c77",)


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
    ledger: Ledger, company_id: int, name: str = "1c77", lang: str | None = None
) -> int:
    """Create a template's subconto kinds and accounts in one transaction.

    "1c77" is the 1C 7.7 style chart (two-digit codes, subaccounts like 60.1).
    Names come in the given language (default: the interface language).
    """
    if name not in TEMPLATES:
        raise ValidationError(
            tr("нет шаблона {name}; есть: {names}", name=name, names=list(TEMPLATES))
        )
    lang = lang or language()
    with transaction(ledger.conn):
        kinds_file = TEMPLATES_DIR / f"chart_{name}_subconto_{lang}.csv"
        for row in _read_rows(kinds_file, SUBCONTO_COLUMNS, ";"):
            ledger.add_subconto_kind(company_id, row["code"].strip(), row["name"].strip())
        return import_chart_csv(ledger, company_id, TEMPLATES_DIR / f"chart_{name}_{lang}.csv")


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
                    parent_code=(row["parent"] or "").strip() or None,
                    is_group=(row["group"] or "").strip() == "1",
                    subconto=[ledger.subconto_kind_id(company_id, k) for k in kinds],
                    account_class=account_class,
                    contra=(row.get("contra") or "").strip() == "1",
                    two_sided=two_sided,
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
