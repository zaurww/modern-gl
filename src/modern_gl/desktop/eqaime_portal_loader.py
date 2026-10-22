"""Talking to the tax portal off the window's thread: the e-qaimə of a period, and what
changed on the portal in the months already reconciled."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QObject, Signal

from modern_gl.application.eqaime_import import (
    EInvoice,
    parse_invoice,
)
from modern_gl.domain.dates import month_name
from modern_gl.domain.eqaime import IMPORTED, PortalInvoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient, PortalError
from modern_gl.reporting.eqaime_reconciliation import changed_after_reconciliation


def fetch_invoices(
    client: EtaxesClient,
    date_from: date,
    date_to: date,
    purchases: bool,
    sales: bool,
    progress: Callable[[str], None],
) -> list[EInvoice]:
    """The e-qaimə of the period with their lines: received (purchases), sent (sales)."""
    result = []
    for outgoing, wanted in ((False, purchases), (True, sales)):
        if not wanted:
            continue
        rows = list(client.invoices(outgoing, date_from, date_to, IMPORTED))
        for n, row in enumerate(rows, 1):
            progress(tr("Загружено e-qaimə: {n} из {total}", n=n, total=len(rows)))
            detail = client.detail(str(row.get("id")), str(row.get("sourceSystem") or "avis"))
            result.append(parse_invoice(row, detail, outgoing))
    return result


@dataclass
class Fetched:
    invoices: list[EInvoice]
    rechecked: list[PortalInvoice]  # the reconciled months read again


def changes_warning(conn: sqlite3.Connection, company_id: int) -> str:
    """'' or what changed on the portal in the months marked reconciled."""
    changed = changed_after_reconciliation(conn, company_id)
    if not changed:
        return ""
    months = [
        tr(
            "{month}, {direction}: {n}",
            month=month_name(c.month),
            direction=tr("продажи") if c.outgoing else tr("покупки"),
            n=len(c.numbers),
        )
        for c in changed
    ]
    return tr(
        "После сверки на портале изменились e-qaimə — {months}. "
        "Откройте «Сверку с порталом» за этот месяц.",
        months="; ".join(months),
    )


class PortalLoader(QObject):
    """Runs a job that talks to the portal off the window's thread."""

    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            self.loaded.emit(self.job(self.progress.emit))
        except PortalError as exc:
            self.failed.emit(str(exc))
