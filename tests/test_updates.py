"""A newer version offered in the sidebar (D191): what GitHub's answer means, once
a day, the download and the installer's start — with a fake GitHub and a pool that runs at
once."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton

from modern_gl import __version__
from modern_gl.application import updates
from modern_gl.application.updates import Release
from modern_gl.desktop.preferences import UPDATES_CHECKED, Preferences
from modern_gl.desktop.updater import Sources, Updater

SETUP_URL = "https://github.com/zaurww/modern-gl/releases/download/v9.9.9/modern-gl-9.9.9-setup.exe"


def github(version: str = "9.9.9", installer: bool = True) -> bytes:
    assets: list[dict[str, object]] = [
        {"name": "modern-gl-9.9.9-windows.zip", "browser_download_url": "https://x/z.zip"}
    ]
    if installer:
        assets.append(
            {
                "name": f"modern-gl-{version}-setup.exe",
                "browser_download_url": SETUP_URL,
                "size": 150,
            }
        )
    return json.dumps({"tag_name": f"v{version}", "assets": assets}).encode()


# ---- the meaning of a release --------------------------------------------------------


def test_the_release_is_its_installer():
    assert updates.parse_release(github()) == Release("9.9.9", SETUP_URL, 150)
    assert updates.parse_release(github(installer=False)) is None


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("0.1.4", "0.1.3", True),
        ("0.1.10", "0.1.9", True),
        ("0.2.0", "0.1.9", True),
        ("0.1.3", "0.1.3", False),
        ("0.1.2", "0.1.3", False),
        ("1.0.0-rc1", "0.9.9", True),
    ],
)
def test_newer_is_by_numbers(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


def test_once_a_day():
    today = date(2026, 11, 3)
    assert updates.due("", today)
    assert updates.due("2026-11-02", today)
    assert not updates.due("2026-11-03", today)


def test_nothing_is_offered_without_a_connection_or_a_newer_version():
    def no_network() -> bytes:
        raise OSError("no connection")

    assert updates.newer_release("0.1.3", no_network) is None
    assert updates.newer_release("0.1.3", lambda: b"not json") is None
    assert updates.newer_release("9.9.9", github) is None
    assert updates.newer_release("0.1.3", github) == Release("9.9.9", SETUP_URL, 150)


def test_the_installer_runs_quietly_and_the_program_comes_back():
    setup, program = Path("C:/Temp/modern-gl-9.9.9-setup.exe"), Path("C:/P/modern-gl.exe")
    command = updates.install_command(setup, program)
    assert command[:2] == ["cmd", "/c"]
    line = command[2]
    assert f'/wait "{setup}" /SILENT /CLOSEAPPLICATIONS' in line
    assert line.endswith(f'& start "" "{program}"')


# ---- the sidebar's line --------------------------------------------------------------


class AtOnce:
    """A pool that runs the job in the test's thread."""

    def start(self, job) -> None:
        job.run()


class Fake:
    def __init__(self, tmp_path: Path, fetch=github, fail_download: bool = False) -> None:
        self.fetches = 0
        self.fetch_body = fetch
        self.fail_download = fail_download
        self.commands: list[list[str]] = []
        self.quits = 0
        self.progress: list[tuple[int, int]] = []
        self.tmp_path = tmp_path

    def fetch(self) -> bytes:
        self.fetches += 1
        return self.fetch_body()

    def download(self, url: str, target: Path, progress) -> Path:
        if self.fail_download:
            raise OSError("connection lost")
        assert url == SETUP_URL
        for done in (50, 100, 150):
            progress(done, 150)
            self.progress.append((done, 150))
        target.write_bytes(b"setup")
        return target

    def run(self, command: list[str]) -> None:
        self.commands.append(command)

    def quit(self) -> None:
        self.quits += 1


def make(qtbot, tmp_path: Path, fake: Fake, installed: bool = True) -> tuple[QPushButton, Updater]:
    line = QPushButton()
    qtbot.addWidget(line)
    prefs = Preferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
    sources = Sources(
        fetch=fake.fetch,
        download=fake.download,
        run=fake.run,
        installed=installed,
        today=lambda: date(2026, 11, 3),
        folder=tmp_path,
        pool=AtOnce(),
    )
    updater = Updater(line, prefs, fake.quit, sources)
    return line, updater


def test_a_newer_version_is_offered_then_installed(qtbot, tmp_path):
    fake = Fake(tmp_path)
    line, updater = make(qtbot, tmp_path, fake)
    updater.start()
    assert line.isVisibleTo(line) and "9.9.9" in line.text()
    assert updater.prefs.text(UPDATES_CHECKED) == "2026-11-03"

    line.click()
    assert (tmp_path / "modern-gl-9.9.9-setup.exe").read_bytes() == b"setup"
    assert fake.progress[-1] == (150, 150)
    assert len(fake.commands) == 1 and "modern-gl-9.9.9-setup.exe" in fake.commands[0][2]
    assert fake.quits == 1


def test_the_look_is_once_a_day(qtbot, tmp_path):
    fake = Fake(tmp_path)
    _line, updater = make(qtbot, tmp_path, fake)
    updater.start()
    updater.start()
    assert fake.fetches == 1


def test_nothing_is_shown_when_run_from_the_source(qtbot, tmp_path):
    fake = Fake(tmp_path)
    line, updater = make(qtbot, tmp_path, fake, installed=False)
    updater.start()
    assert fake.fetches == 0 and line.isHidden()


def test_nothing_is_shown_without_a_newer_version(qtbot, tmp_path):
    fake = Fake(tmp_path, fetch=lambda: github(__version__))
    line, updater = make(qtbot, tmp_path, fake)
    updater.start()
    assert line.isHidden()


def test_a_failed_download_can_be_tried_again(qtbot, tmp_path):
    fake = Fake(tmp_path, fail_download=True)
    line, updater = make(qtbot, tmp_path, fake)
    updater.start()
    line.click()
    assert line.isEnabled() and fake.commands == [] and fake.quits == 0
    assert "обновление" in line.text() or "yenilə" in line.text().lower()


def test_the_sidebar_keeps_the_line_hidden_until_needed(demo_window):
    assert demo_window.sidebar.new_version.isHidden()
