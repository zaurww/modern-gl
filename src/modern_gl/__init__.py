"""Modern GL — the version the program shows, logs and puts into an error report.

`pyproject.toml` is the only place the version is written (`uv version 0.1.1` changes it
and `uv.lock`); the installed metadata brings it here, the frozen build copies that
metadata (`packaging/modern-gl.spec`), the tag `v<version>` builds the release
(`.github/workflows/release.yml`, `scripts/release.py`)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("modern-gl")
except PackageNotFoundError:  # the sources without an install
    __version__ = "0.0.0"
