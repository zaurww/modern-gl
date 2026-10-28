"""The Central Bank's rates for many days off the window's thread: a request a day (a
year — a few minutes), the window stays alive and says how far it is. Days the company
has every rate of are not asked again. Used by «Валюты» and the bank's file window."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta

from PySide6.QtCore import QObject

from modern_gl.application.currencies import days_without_rate
from modern_gl.desktop.portal_worker import PortalRun, run_on_portal
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.cbar import RatesUnavailableError
from modern_gl.infrastructure.etaxes import PortalError

MAX_DAYS = 366  # a year at most: one request a day
Rates = dict[str, tuple[int, int]]


def days_to_load(session: Session, first: date, last: date) -> list[str]:
    """The days of the period some active currency of the company has no rate of."""
    codes = [c.code for c in session.catalog.currencies.values() if c.active]
    days = [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]
    missing = days_without_rate(session.conn, session.company_id, _pairs(codes, days))
    return sorted({day for found in missing.values() for day in found})


def _pairs(codes: Iterable[str], days: list[str]) -> list[tuple[str, str]]:
    return [(code, day) for code in codes for day in days]


def load_rates(
    session: Session,
    parent: QObject,
    days: list[str],
    progress: Callable[[str], None],
    done: Callable[[int], None],
    failed: Callable[[str], None],
) -> PortalRun:
    """Fetch the days in the background, write them here: `done` gets how many days were
    set; no connection — `failed` (said once, not for every day)."""
    fetch = session.fetch_rates

    def job(say: Callable[[str], None]) -> dict[str, Rates]:
        got: dict[str, Rates] = {}
        for n, day in enumerate(days, 1):
            say(tr("Курсы ЦБА: {n} из {total}", n=n, total=len(days)))
            try:
                got[day] = fetch(date.fromisoformat(day))
            except RatesUnavailableError as e:  # a day without rates is skipped;
                if "cbar.az" in str(e):  # no connection: said, not tried every day
                    raise PortalError(str(e)) from e
        return got

    def fetched(got: object) -> None:
        assert isinstance(got, dict)
        loaded = 0
        try:
            for day, rates in sorted(got.items()):
                if session.ledger.import_rates(session.company_id, date.fromisoformat(day), rates):
                    loaded += 1
        except LedgerError as e:
            failed(str(e))
            return
        done(loaded)

    return run_on_portal(parent, job, progress, fetched, failed)
