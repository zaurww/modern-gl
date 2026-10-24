"""The books (D7, D63): a book is a set of layers, and «in the book» has one meaning for
every reader — the posted documents of those layers up to a day (`docs_cte`). The
reports, the write scenarios that need a balance (revaluation) and the assistant all
read the books through here."""

from __future__ import annotations

import json

from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

COMMON = ("common",)
IFRS = ("common", "ifrs_adj")
TAX = ("common", "tax_adj")
BOOKS = {"common": COMMON, "ifrs": IFRS, "tax": TAX}  # by the name a file or a client uses

FROM, AFTER = "from", "after"  # where `docs_cte` starts: :date_from, the day after :after


def docs_cte(
    columns: str = "d.id",
    *,
    start: str = "",
    every_layer: bool = False,
    status: str = "'posted'",
) -> str:
    """`docs AS (…)`: the posted documents of the requested book (:layers) up to :date_to —
    the one meaning of «in the book» for every report. `start` — FROM :date_from or AFTER
    :after (else from the beginning); `every_layer` — all the books (the caller tells
    them apart by `l.code`); `status` — another SQL value instead of posted."""
    since = {
        "": "",
        FROM: "\n      AND d.doc_date >= :date_from",
        AFTER: "\n      AND d.doc_date > :after",
    }[start]
    book = "" if every_layer else "\n      AND l.code IN (SELECT value FROM json_each(:layers))"
    return f"""
docs AS (
    SELECT {columns}
    FROM documents d
    JOIN layers l ON l.id = d.layer_id
    WHERE d.company_id = :company_id
      AND d.status = {status}{since}
      AND d.doc_date <= :date_to{book}
)"""


def book_params(conn: Connection, company_id: int, date_from, date_to, layers) -> dict:
    """The parameters of `docs_cte` for a period of a book; the dates checked, the layers
    known to the company."""
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    known = {
        r["code"]
        for r in conn.execute("SELECT code FROM layers WHERE company_id = ?", (company_id,))
    }
    unknown = set(layers) - known
    if unknown:
        raise NotFoundError(tr("неизвестные слои: {layers}", layers=sorted(unknown)))
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "layers": json.dumps(list(layers)),
    }
