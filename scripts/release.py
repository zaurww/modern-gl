"""Cut a release:  uv run python scripts/release.py 0.1.1 [--push]

The version is written in one place, `pyproject.toml` (`uv version` sets it there and in
`uv.lock`); the program shows it (`modern_gl.__version__`). On a clean `master` the script
sets the version, checks that `CHANGELOG.md` has its section `## [0.1.1]`, commits
«Версия 0.1.1» and tags `v0.1.1`. `--push` sends `master` and the tag: the tag starts
`.github/workflows/release.yml`, which builds the installer and the zip into a GitHub
Release (about ten minutes). Without `--push` the command to run is printed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def run(*args: str) -> str:
    done = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)  # noqa: S603
    return done.stdout


def check_tree() -> None:
    branch = run("git", "branch", "--show-current").strip()
    if branch != "master":
        sys.exit(f"Релиз — только из master (сейчас {branch})")
    if run("git", "status", "--porcelain").strip():
        sys.exit("Есть незакоммиченные изменения — сначала закоммитить или убрать")


def check_changelog(version: str) -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in text:
        sys.exit(f"В CHANGELOG.md нет раздела «## [{version}] — дата» — сначала описать изменения")


def main(argv: list[str]) -> None:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or not VERSION.match(args[0]):
        sys.exit(__doc__)
    version = args[0]
    check_tree()
    check_changelog(version)
    if run("git", "tag", "--list", f"v{version}").strip():
        sys.exit(f"Тег v{version} уже есть")
    run("uv", "version", version)
    if run("git", "status", "--porcelain").strip():  # the version was not this one yet
        run("git", "add", "pyproject.toml", "uv.lock")
        run("git", "commit", "-m", f"Версия {version}")
    run("git", "tag", "-a", f"v{version}", "-m", f"Modern GL {version}")
    if "--push" in argv:
        run("git", "push", "origin", "master", f"v{version}")
        print(f"v{version} отправлен; сборка — https://github.com/zaurww/modern-gl/actions")
    else:
        print(f"Готово: коммит и тег v{version}. Отправить: git push origin master v{version}")


if __name__ == "__main__":
    main(sys.argv[1:])
