"""The program's releases on GitHub (D-new-updates): the latest one and its installer.
Network only — what a release means for the running program is `application/updates`."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

LATEST_URL = "https://api.github.com/repos/zaurww/modern-gl/releases/latest"
TIMEOUT = 8  # seconds: a look for a new version must never hold the program
CHUNK = 1 << 20

Progress = Callable[[int, int], None]  # bytes received, bytes in all (0: unknown)


def fetch_latest(url: str = LATEST_URL) -> bytes:
    """The JSON of the latest release. OSError when there is no connection or no release."""
    return _open(url, lambda response: response.read())


def download(url: str, target: Path, progress: Progress | None = None) -> Path:
    """Save the file at `url` as `target`: written as `.part` beside it, renamed when
    complete, so a broken download never looks like an installer."""
    part = target.with_name(target.name + ".part")

    def save(response: Any) -> None:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with part.open("wb") as out:
            while chunk := response.read(CHUNK):
                out.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)

    _open(url, save)
    part.replace(target)
    return target


def _open(url: str, use: Callable[[Any], Any]) -> Any:
    if not url.startswith("https://"):
        raise ValueError(f"GitHub is reached only over https: {url}")
    # S310: the scheme is checked just above
    request = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "Modern GL", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return use(response)
    except urllib.error.HTTPError as e:
        raise OSError(f"GitHub: {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OSError(str(e)) from e
