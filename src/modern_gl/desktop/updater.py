"""A newer version offered at the bottom of the sidebar (D191): looked for at every start
and then every hour in the background — a fix must reach the colleague at once, not
tomorrow; a click downloads the installer and runs it quietly — the program
closes and comes back updated, the company files are not touched. Only the installed
program is updated, never a run from the source."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QPushButton

from modern_gl import __version__
from modern_gl.application import updates
from modern_gl.application.updates import Release
from modern_gl.desktop.preferences import Preferences
from modern_gl.i18n import tr
from modern_gl.infrastructure import github_releases
from modern_gl.infrastructure.github_releases import Progress

logger = logging.getLogger(__name__)

EVERY = 60 * 60 * 1000  # ms between looks while the program stays open

Fetch = Callable[[], bytes]
Download = Callable[[str, Path, Progress], Path]
Run = Callable[[str], None]


class _Relay(QObject):
    """Lives in the window's thread: what a job sends arrives there."""

    done = Signal(object)
    progress = Signal(int, int)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, job: Callable[[], Any], relay: _Relay) -> None:
        super().__init__()
        self.job, self.relay = job, relay

    def run(self) -> None:
        try:
            result = self.job()
        except Exception as e:  # the window must not go with a download
            logger.warning("update: %s", e)
            self.relay.failed.emit(str(e))
            return
        self.relay.done.emit(result)


def _start(command: str) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console behind cmd
    subprocess.Popen(command, creationflags=flags)  # noqa: S603 — our own installer


def _temp() -> Path:
    return Path(tempfile.gettempdir())


@dataclass
class Sources:
    """Where the updater reaches out: GitHub, the disk, the installer; tests give fakes."""

    fetch: Fetch = github_releases.fetch_latest
    download: Download = github_releases.download
    run: Run = _start
    installed: bool = field(default_factory=updates.installed_build)
    folder: Path = field(default_factory=_temp)
    pool: Any = None  # the application's thread pool when None


class Updater(QObject):
    """`line` is the sidebar's button: hidden, then «Вышла версия … — обновить», then the
    download's progress. Everything slow runs in the pool, the line is touched only here."""

    def __init__(
        self,
        line: QPushButton,
        prefs: Preferences,
        quit: Callable[[], None],
        sources: Sources | None = None,
    ) -> None:
        super().__init__(line)
        self.line, self.prefs, self.quit = line, prefs, quit
        self.sources = sources or Sources()
        self.pool = self.sources.pool or QThreadPool.globalInstance()
        self.release: Release | None = None
        self.check_relay, self.load_relay = _Relay(), _Relay()
        self.check_relay.done.connect(self._found)
        self.load_relay.done.connect(self._downloaded)
        self.load_relay.progress.connect(self._progress)
        self.load_relay.failed.connect(self._failed)
        self.timer = QTimer(self)
        self.timer.setInterval(EVERY)
        self.timer.timeout.connect(self.check)
        self.line.hide()
        self.line.clicked.connect(self.install)

    def start(self) -> None:
        """Look for a newer version now and then every hour — in the background, silently
        when there is none or no connection."""
        if not self.sources.installed:
            return
        self.timer.start()  # before the look: a pool that runs at once may stop it
        self.check()

    def check(self) -> None:
        fetch = self.sources.fetch
        self.pool.start(_Job(lambda: updates.newer_release(__version__, fetch), self.check_relay))

    def install(self) -> None:
        """Download the installer and run it; the program quits — the installer closes it
        anyway — and comes back when the setup is done."""
        if self.release is None:
            return
        self.line.setEnabled(False)
        self.line.setText(tr("Скачиваем версию {version}…", version=self.release.version))
        url = self.release.setup_url
        target = updates.setup_path(self.release, self.sources.folder)
        download, progress = self.sources.download, self.load_relay.progress.emit
        self.pool.start(_Job(lambda: download(url, target, progress), self.load_relay))

    def _found(self, release: object) -> None:
        if not isinstance(release, Release):
            return
        self.release = release
        self.timer.stop()  # found: the line stays until the click
        self.line.setText(tr("Вышла версия {version} — обновить", version=release.version))
        self.line.setEnabled(True)
        self.line.show()

    def _progress(self, done: int, total: int) -> None:
        if self.release is not None and total:
            percent = min(100, done * 100 // total)
            version = self.release.version
            text = tr("Скачиваем версию {version}… {percent}%", version=version, percent=percent)
            self.line.setText(text)

    def _downloaded(self, setup: object) -> None:
        self.line.setText(tr("Устанавливаем…"))
        self.sources.run(updates.install_command(Path(str(setup)), Path(sys.executable)))
        self.quit()

    def _failed(self, error: str) -> None:
        logger.warning("update download failed: %s", error)
        self.line.setEnabled(True)
        self.line.setText(tr("Не удалось скачать обновление — попробовать ещё раз"))
