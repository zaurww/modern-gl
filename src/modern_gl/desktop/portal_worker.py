"""One job on the tax portal off the window's thread — the window stays alive while it
talks (e-qaimə import, reconciliation, ƏDV deposit). Before, each window built its own
QThread + moveToThread; a window closed while its thread still ran took the thread with it
("QThread: Destroyed while thread is still running" ends the program).

Now the thread belongs to no window: it is kept here until it finishes. The window's side
(`PortalRun`) is its child, so a closed window gets nothing more — Qt drops the
connections of a destroyed object."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Slot

from modern_gl.desktop.eqaime_portal_loader import PortalLoader

Job = Callable[[Callable[[str], None]], object]

# threads not finished yet and their loaders: nothing else holds them
_RUNNING: dict[QThread, PortalLoader] = {}


class PortalRun(QObject):
    """What the window hears of one job: progress…, then loaded or failed."""

    def __init__(
        self,
        parent: QObject,
        progress: Callable[[str], None],
        loaded: Callable[[Any], None],
        failed: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._progress, self._loaded, self._failed = progress, loaded, failed
        self.done = False

    @Slot(str)
    def on_progress(self, text: str) -> None:
        self._progress(text)

    @Slot(object)
    def on_loaded(self, result: object) -> None:
        self.done = True
        self._loaded(result)

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.done = True
        self._failed(message)


def run_on_portal(
    parent: QObject,
    job: Job,
    progress: Callable[[str], None],
    loaded: Callable[[Any], None],
    failed: Callable[[str], None],
) -> PortalRun:
    """Start `job(progress)` in a thread of its own; its outcome comes to `loaded` (the
    result) or `failed` (the message) on the window's thread."""
    run = PortalRun(parent, progress, loaded, failed)
    thread = QThread()
    loader = PortalLoader(job)
    loader.moveToThread(thread)
    thread.started.connect(loader.run)
    loader.progress.connect(run.on_progress)
    loader.loaded.connect(run.on_loaded)
    loader.failed.connect(run.on_failed)
    for signal in (loader.loaded, loader.failed):  # quit is thread-safe: called at once,
        signal.connect(thread.quit, Qt.ConnectionType.DirectConnection)  # not queued
    thread.finished.connect(loader.deleteLater)
    thread.finished.connect(lambda: _finished(thread))
    _RUNNING[thread] = loader
    thread.start()
    return run


def _finished(thread: QThread) -> None:
    _RUNNING.pop(thread, None)
    thread.deleteLater()


def wait_all() -> None:
    """Every portal thread finished (on quitting, in tests)."""
    for thread in list(_RUNNING):
        thread.wait()
