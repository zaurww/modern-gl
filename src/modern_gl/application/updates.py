"""A newer version of the program (D-new-updates): what the latest release on GitHub means
for the one running. Pure — the network is `infrastructure/github_releases`, the line in the
sidebar and the installer's start are `desktop/updater`."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SETUP_SUFFIX = "-setup.exe"


@dataclass(frozen=True)
class Release:
    version: str
    setup_url: str
    size: int  # bytes of the installer, 0 when GitHub did not say


def parse_release(body: bytes) -> Release | None:
    """The release in GitHub's JSON, or None when it carries no installer."""
    data = json.loads(body)
    version = str(data.get("tag_name", "")).removeprefix("v")
    for asset in data.get("assets") or []:
        url = asset.get("browser_download_url")
        if str(asset.get("name", "")).endswith(SETUP_SUFFIX) and url:
            return Release(version, str(url), int(asset.get("size") or 0))
    return None


def version_key(version: str) -> tuple[int, ...]:
    """«0.1.10» after «0.1.9»: numbers, not text; a suffix («-rc1») is ignored."""
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    return version_key(latest) > version_key(current)


def due(checked: str, today: date) -> bool:
    """Once a day: `checked` is the day of the last look (ISO date), empty at first."""
    return checked != today.isoformat()


def newer_release(current: str, fetch: Callable[[], bytes]) -> Release | None:
    """The release to offer, or None: nothing newer, no installer in it, no connection —
    quietly, an update is never urgent."""
    try:
        release = parse_release(fetch())
    except (OSError, ValueError):
        return None
    if release is None or not is_newer(release.version, current):
        return None
    return release


def installed_build() -> bool:
    """The program as installed (frozen by PyInstaller), not run from the source."""
    return bool(getattr(sys, "frozen", False))


def setup_path(release: Release, folder: Path) -> Path:
    return folder / f"modern-gl-{release.version}{SETUP_SUFFIX}"


def install_command(setup: Path, program: Path) -> list[str]:
    """Run the installer quietly — it closes the program itself (Inno, CloseApplications)
    and shows only its progress — then start the program again, updated or not (a cancelled
    setup gives the old one back): a line for cmd, which waits in between."""
    silent = f'"{setup}" /SILENT /CLOSEAPPLICATIONS /NORESTART /SP-'
    return ["cmd", "/c", f'start "" /wait {silent} & start "" "{program}"']
