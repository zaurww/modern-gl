"""Cut a release:  uv run python scripts/release.py 0.1.1 [--push]

The version is written in one place, `pyproject.toml` (`uv version` sets it there and in
`uv.lock`); the program shows it (`modern_gl.__version__`). On a clean `master` the script
sets the version, checks that `CHANGELOG.md` has its section `## [0.1.1]`, commits
«Версия 0.1.1» and tags `v0.1.1`. `--push` sends `master` and the tag: the tag starts
`.github/workflows/release.yml`, which builds the installer and the zip into a GitHub
Release (about ten minutes). Without `--push` the command to run is printed.

The Release comes out as a trial version (GitHub: «pre-release»): only a computer with
«Пробные версии программы» switched on is offered it. Tried there on a copy of real work,
it is given to everyone:  uv run python scripts/release.py 0.1.1 --publish  (needs `gh`).
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


def publish(version: str) -> None:
    """The trial version becomes the latest one: every installed program is offered it."""
    try:
        run("gh", "release", "edit", f"v{version}", "--prerelease=false", "--latest")
    except FileNotFoundError:
        sys.exit("Нет программы gh (GitHub CLI) — снять «pre-release» на странице релиза")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Релиз v{version} не выпущен для всех: {e.stderr.strip()}")
    print(f"v{version} — для всех: программы предложат обновление в течение часа")


def main(argv: list[str]) -> None:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or not VERSION.match(args[0]):
        sys.exit(__doc__)
    version = args[0]
    if "--publish" in argv:
        publish(version)
        return
    check_tree()
    check_changelog(version)
    if run("git", "tag", "--list", f"v{version}").strip():
        sys.exit(f"Тег v{version} уже есть")
    # --no-sync: the lock gets the version, the environment is not rebuilt (a running
    # modern-gl-mcp holds its exe)
    run("uv", "version", version, "--no-sync")
    run("git", "add", "pyproject.toml", "uv.lock")
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False)  # noqa: S607
    if staged.returncode:  # the version was not this one yet
        run("git", "commit", "-m", f"Версия {version}")
    run("git", "tag", "-a", f"v{version}", "-m", f"Modern GL {version}")
    if "--push" in argv:
        run("git", "push", "origin", "master", f"v{version}")
        print(f"v{version} отправлен; сборка — https://github.com/zaurww/modern-gl/actions")
        print(f"Выйдет пробной версией; выпустить для всех: release.py {version} --publish")
    else:
        print(f"Готово: коммит и тег v{version}. Отправить: git push origin master v{version}")


if __name__ == "__main__":
    main(sys.argv[1:])
