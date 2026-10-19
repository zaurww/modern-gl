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


def import_chart_csv(
    ledger: Ledger, company_id: int, path: str | Path, delimiter: str = ";"
) -> int:
    """Import all accounts atomically; returns the number of accounts added."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        missing = set(COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValidationError(f"в CSV нет колонок: {sorted(missing)}")
        rows = list(reader)

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
