"""`requirements.txt` is generated from `uv.lock`, never written by hand (README, «Запуск
и проверки»): `uv export --no-dev --format requirements-txt --no-hashes -o requirements.txt`.
The test reads the lock (TOML) and checks that the file pins exactly the packages the
program needs, at the lock's versions — a `uv add` or `uv lock -U` without the export fails."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROJECT = "modern-gl"


def locked() -> dict[str, dict]:
    with (ROOT / "uv.lock").open("rb") as f:
        return {p["name"]: p for p in tomllib.load(f)["package"]}


def runtime_closure(packages: dict[str, dict]) -> dict[str, str]:
    """Every package the project depends on, directly or through another (not the dev
    group), with its locked version."""
    found: dict[str, str] = {}
    pending = [d["name"] for d in packages[PROJECT].get("dependencies", [])]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found[name] = packages[name]["version"]
        pending += [d["name"] for d in packages[name].get("dependencies", [])]
    return found


def pinned() -> dict[str, str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)$", text, flags=re.MULTILINE))


def test_requirements_pin_the_locked_versions() -> None:
    assert pinned() == runtime_closure(locked()), (
        "requirements.txt differs from uv.lock: "
        "uv export --no-dev --format requirements-txt --no-hashes -o requirements.txt"
    )


def test_requirements_install_the_project_itself() -> None:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "-e ." in lines
    assert not any(line.startswith("pytest") for line in lines), "dev packages are not pinned"
