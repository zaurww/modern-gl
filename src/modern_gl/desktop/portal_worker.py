"""One job on the tax portal off the window's thread — the window stays alive while it
talks (e-qaimə import, reconciliation, ƏDV deposit). Before, each window built its own
QThread + moveToThread; a window closed while its thread still ran took the thread with it
("QThread: Destroyed while thread is still running" ends the program).

Now the thread belongs to no window: it is kept here until it finishes. The window's side
(`PortalRun`) is its child, so a closed window gets nothing more — Qt drops the
connections of a destroyed object.

The thread and its loader die on the window's thread only, after the thread is joined
(`_finished`). Before, `thread.finished → loader.deleteLater` destroyed the loader's C++
object inside the worker thread while Python still held its wrapper on the window's
thread: two threads over one object's lifetime, and once in a while CI's pytest-xdist
worker died with it (`test_currency_ui`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Slot
from shiboken6 import delete, isValid

from modern_gl.desktop.eqaime_portal_loader import PortalLoader

Job = Callable[[Callable[[str], None]], object]

# threads not finalized yet, by the wrapper's id, with their loaders: nothing else
# holds them, so nothing of them is freed from another thread
_RUNNING: dict[int, tuple[QThread, PortalLoader]] = {}


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
    # a Python callable, not a slot: Qt queues it to the window's thread
    thread.finished.connect(lambda: _finished(id(thread)))
    _RUNNING[id(thread)] = (thread, loader)
    thread.start()
    return run


def _finished(key: int) -> None:
    """On the window's thread, once the worker's loop ended: join the thread, then delete
    the loader and the thread here — the loader is not deleted from the thread it lived
    in, and nothing of it runs any more."""
    found = _RUNNING.pop(key, None)
    if found is None:
        return  # finalized by `wait_all` already
    thread, loader = found
    thread.wait()
    if isValid(loader):
        delete(loader)
    if isValid(thread):
        thread.deleteLater()


def wait_all() -> None:
    """Every portal thread finished and finalized (on quitting, in tests): the queued
    `_finished` of a thread joined here finds nothing left to do."""
    for key, (thread, _loader) in list(_RUNNING.items()):
        thread.wait()
        _finished(key)
