"""Saved views of a report (D190): the splits, the order and the
columns of the trial balance kept under a name in the company's file."""

from __future__ import annotations

import json
from collections.abc import Mapping

from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import insert, transaction


class ReportViewCommands(LedgerBase):
    """Use cases of saved views: save under a name (a view of that name is replaced),
    delete."""

    def save_report_view(
        self, company_id: int, report: str, name: str, settings: Mapping[str, object]
    ) -> int:
        """The settings under a name; a view of that name (any case) is replaced."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название вида не может быть пустым"))
        text = json.dumps(settings, ensure_ascii=False)
        with transaction(self.conn):
            # the same name in another case (Cyrillic and Azerbaijani letters too: not
            # SQLite's NOCASE) is the same view
            found = next(
                (
                    r["id"]
                    for r in self.conn.execute(
                        "SELECT id, name FROM report_views WHERE company_id = ? AND report = ?",
                        (company_id, report),
                    )
                    if fold(r["name"]) == fold(name)
                ),
                None,
            )
            if found is not None:
                self.conn.execute(
                    "UPDATE report_views SET name = ?, settings = ? "
                    "WHERE company_id = ? AND id = ?",
                    (name, text, company_id, found),
                )
                return found
            return insert(
                self.conn,
                "INSERT INTO report_views (company_id, report, name, settings) VALUES (?, ?, ?, ?)",
                (company_id, report, name, text),
            )

    def delete_report_view(self, company_id: int, view_id: int) -> None:
        """The view is gone; the books do not notice."""
        with transaction(self.conn):
            gone = self.conn.execute(
                "DELETE FROM report_views WHERE company_id = ? AND id = ?", (company_id, view_id)
            ).rowcount
        if not gone:
            raise NotFoundError(tr("вид отчёта не найден"))
