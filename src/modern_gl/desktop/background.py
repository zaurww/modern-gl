"""Heavy reading off the window's thread (debt 6, D24: by measurements). A large company's
report is read in a worker on a connection of its own to the same file (read-only); the
window stays alive meanwhile and gets the result in its own thread. A small company — and
a company open for viewing, which lives in memory — reads at once, as before.

Measured (scripts/benchmark.py, session 38): with 100 000 postings «Bu gün», e-qaimə, the
journal and a year's card take 1–2.5 s; at the demo year's ~8 000 every report is under
0.15 s. LARGE is where the first ones pass ~0.3 s.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from traceback import format_exception
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from shiboken6 import isValid

from modern_gl.desktop import crash_dialog
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import Connection, connect_reader

logger = logging.getLogger(__name__)
LARGE = 20_000  # postings of a company: from here on, reports are read in the background

Job = Callable[[Connection], Any]


class _Relay(QObject):
    """Lives in the window's thread: what the worker sends arrives there."""

    # owner's key (an id: too big for Qt's int), the run's number, the result
    done = Signal(object, int, object)
    failed = Signal(object, int, object)


class _Worker(QRunnable):
    def __init__(
        self, path: Path, job: Job, key: int, run: int, relay: _Relay, last: dict[int, int]
    ) -> None:
        super().__init__()
        self.path, self.job, self.key, self.run_no = path, job, key, run
        self.relay, self.last = relay, last

    def run(self) -> None:
        if self.last.get(self.key) != self.run_no:
            return  # refreshed again while it waited: only the newest is read
        conn = connect_reader(self.path)
        try:
            result: object = self.job(conn)
            signal = self.relay.done
        except LedgerError as e:
            result, signal = e, self.relay.failed
        except Exception as e:  # a failure of the program: the window must not go with it
            logger.exception("background read failed")
            result, signal = e, self.relay.failed
        finally:
            conn.close()
        with suppress(RuntimeError):  # the company was closed (the window quit) meanwhile
            signal.emit(self.key, self.run_no, result)


class Background:
    """One per open company: the last run of each owner wins (a page refreshed twice shows
    the second result only). One worker thread: two readers at once would fight over
    Python's lock and both take many times longer (measured: 2.5 s alone, 24 s as two)."""

    def __init__(self) -> None:
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._relay = _Relay()
        self._relay.done.connect(self._done)
        self._relay.failed.connect(self._failed)
        self._last: dict[int, int] = {}
        self._handlers: dict[tuple[int, int], tuple[QObject, Callable, Callable]] = {}

    def run(
        self,
        owner: QObject,
        conn: Connection,
        path: Path | None,
        large: bool,
        job: Job,
        done: Callable[[Any], None],
        failed: Callable[[LedgerError], None],
    ) -> bool:
        """Read `job` and hand its result to `done` (or a LedgerError to `failed`).
        Returns True when it went to the background (the result comes later)."""
        if not large or path is None:
            try:
                result = job(conn)
            except LedgerError as e:
                failed(e)
                return False
            done(result)
            return False
        key = id(owner)
        run = self._last.get(key, 0) + 1
        self._last[key] = run
        self._handlers[(key, run)] = (owner, done, failed)
        self._pool.start(_Worker(path, job, key, run, self._relay, self._last))
        return True

    def _take(self, key: int, run: int):
        handler = self._handlers.pop((key, run), None)
        if handler is None or self._last.get(key) != run:
            return None  # a newer run of the same owner is on its way
        owner, done, failed = handler
        return (done, failed) if isValid(owner) else None  # the page was closed meanwhile

    def _done(self, key: int, run: int, result: object) -> None:
        handler = self._take(key, run)
        if handler is not None:
            handler[0](result)

    def _failed(self, key: int, run: int, error: object) -> None:
        handler = self._take(key, run)
        if handler is None:
            return
        if isinstance(error, LedgerError):
            handler[1](error)
        elif isinstance(error, BaseException):
            # not the page's business: the user sees what happened, the page stays
            crash_dialog.show_crash("".join(format_exception(error)))

    def wait(self) -> None:
        """Every queued read finished (their results still go through the event loop):
        before the company's file is closed, and in tests."""
        self._pool.waitForDone()
