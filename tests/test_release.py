"""The release (D189-release-updates): one version in `pyproject.toml`, shown by the
program and described in `CHANGELOG.md`; the build files name the same program."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import modern_gl
from modern_gl.desktop import crash_dialog

ROOT = Path(__file__).parent.parent


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_the_program_knows_its_version():
    assert modern_gl.__version__ == project_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", modern_gl.__version__)


def test_the_changelog_describes_the_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{project_version()}] — 20" in text, "раздел версии с датой"


def test_an_error_report_starts_with_the_version(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(crash_dialog, "show_crash", shown.append)
    try:
        raise ZeroDivisionError("пример")
    except ZeroDivisionError as error:
        crash_dialog.report_crash(type(error), error, error.__traceback__)
    assert shown[0].startswith(f"Modern GL {modern_gl.__version__}\n")
    assert "ZeroDivisionError" in shown[0]


def test_the_sidebar_shows_the_version(demo_window):
    assert demo_window.sidebar.hint.text().endswith(f"Modern GL {modern_gl.__version__}")


def test_the_build_files_agree():
    spec = (ROOT / "packaging" / "modern-gl.spec").read_text(encoding="utf-8")
    iss = (ROOT / "packaging" / "modern-gl.iss").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'name="modern-gl"' in spec and 'copy_metadata("modern-gl")' in spec
    assert (ROOT / "packaging" / "modern-gl.ico").exists()
    assert (ROOT / "src" / "modern_gl" / "desktop" / "resources" / "app.png").exists()
    assert "modern-gl.exe" in iss and "{app}\\_internal" in iss
    assert "packaging/modern-gl.spec" in workflow and "modern-gl.iss" in workflow
    assert "workflow_dispatch" in workflow and 'tags: ["v*"]' in workflow
