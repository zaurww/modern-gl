"""A backup every hour of work (D-new-safe-copies): the copy on closing is not enough for
a program left open for days. Made in the background by a connection of its own, only when
the company changed; a failure (a damaged file, the second folder gone) is said once, not
every hour."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from modern_gl.application.workspace import Workspace
from modern_gl.i18n import tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.db import Error

logger = logging.getLogger(__name__)

EVERY = 60 * 60 * 1000  # ms between copies while a company stays open


class _Job(QRunnable):
    def __init__(
        self,
        job: Callable[[], Path | None],
        made: Callable[[], None],
        failed: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.job, self.made, self.failed = job, made, failed

    def run(self) -> None:
        try:
            copy = self.job()
        except (backup.BackupError, OSError, Error) as e:
            logger.warning("timed backup: %s", e)
            self.failed(str(e))
            return
        if copy is not None:
            self.made()


class TimedBackup(QObject):
    """`current` gives the file of the company open for writing, or None (none open, or
    one only viewed). One copy at a time, in a thread of its own; `wait` — before the
    company is closed, whose own copy must not meet this one."""

    made = Signal()
    failed = Signal(str)

    def __init__(
        self, workspace: Workspace, current: Callable[[], Path | None], owner: QWidget
    ) -> None:
        super().__init__(owner)
        self.workspace, self.current, self.owner = workspace, current, owner
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.told = False  # a failure is told once, then again only after a copy that worked
        self.made.connect(self._worked)
        self.failed.connect(self._say)
        self.timer = QTimer(self)
        self.timer.setInterval(EVERY)
        self.timer.timeout.connect(self.tick)

    def tick(self) -> None:
        path = self.current()
        if path is None or self.pool.activeThreadCount():
            return
        workspace = self.workspace
        job = _Job(lambda: workspace.timed_backup(path), self.made.emit, self.failed.emit)
        self.pool.start(job)

    def wait(self) -> None:
        self.pool.waitForDone()

    def stop(self) -> None:
        self.timer.stop()
        self.wait()

    def _worked(self) -> None:
        self.told = False

    def _say(self, error: str) -> None:
        if self.told:
            return
        self.told = True
        QMessageBox.warning(
            self.owner, tr("Резервная копия"), tr("Копия не сохранена: {error}", error=error)
        )
