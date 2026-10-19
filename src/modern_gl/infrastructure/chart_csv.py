"""Import a chart of accounts from CSV (Excel 'CSV UTF-8', ';'-separated).

Columns: code;name;parent;kind;group;subconto
  parent   - parent account code, empty for top level (parents must come first)
  kind     - A / P / AP
  group    - 1 for a group (no postings allowed), empty or 0 otherwise
  subconto - subconto kind codes for positions 1..3, comma-separated; must already exist
"""

from __future__ import annotations

import csv
from pathlib import Path

from modern_gl.application.ledger import Ledger
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import transaction

COLUMNS = ("code", "name", "parent", "kind", "group", "subconto")
SUBCONTO_COLUMNS = ("code", "name")
TEMPLATES_DIR = Path(__file__).parent / "templates"
# name -> (chart file, subconto kinds file)
TEMPLATES = {
    "1c77": ("chart_1c77.csv", "chart_1c77_subconto.csv"),
}


def _read_rows(path: str | Path, columns: tuple[str, ...], delimiter: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        missing = set(columns) - set(reader.fieldnames or ())
        if missing:
            raise ValidationError(f"{Path(path).name}: нет колонок {sorted(missing)}")
        return list(reader)


def apply_chart_template(ledger: Ledger, company_id: int, name: str = "1c77") -> int:
    """Create a template's subconto kinds and accounts in one transaction.

    "1c77" is the 1C 7.7 style chart (two-digit codes, subaccounts like 60.1).
    It is a starting point: accounts can be added afterwards.
    """
    if name not in TEMPLATES:
        raise ValidationError(f"нет шаблона {name!r}; есть: {sorted(TEMPLATES)}")
    chart_file, kinds_file = TEMPLATES[name]
    with transaction(ledger.conn):
        for row in _read_rows(TEMPLATES_DIR / kinds_file, SUBCONTO_COLUMNS, ";"):
            ledger.add_subconto_kind(company_id, row["code"].strip(), row["name"].strip())
        return import_chart_csv(ledger, company_id, TEMPLATES_DIR / chart_file)


def import_chart_csv(
    ledger: Ledger, company_id: int, path: str | Path, delimiter: str = ";"
) -> int:
    """Import all accounts atomically; returns the number of accounts added."""
    rows = _read_rows(path, COLUMNS, delimiter)

    with transaction(ledger.conn):
        for line_no, row in enumerate(rows, start=2):
            try:
                kinds = [c.strip() for c in (row["subconto"] or "").split(",") if c.strip()]
                ledger.add_account(
                    company_id,
                    row["code"].strip(),
                    row["name"].strip(),
                    kind=(row["kind"] or "AP").strip().upper(),
                    parent_code=(row["parent"] or "").strip() or None,
                    is_group=(row["group"] or "").strip() == "1",
                    subconto=[ledger.subconto_kind_id(company_id, k) for k in kinds],
                )
            except Exception as e:
                raise ValidationError(f"{Path(path).name}, строка {line_no}: {e}") from e
    return len(rows)
