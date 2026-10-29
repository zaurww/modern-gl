"""Make `docs/decisions/README.md`: the index of decisions, one row per file.

    uv run python scripts/decisions_index.py

A decision is a file `docs/decisions/D<nnn>-<slug>.md` (or `D188<n>-<slug>.md` in a branch,
D131) that starts with `# D<n> — <title>` and a `Статус:` line. The index is generated, never
edited by hand; `tests/test_decisions.py` fails when it is out of date.
"""

from __future__ import annotations

import re
from pathlib import Path

DECISIONS = Path(__file__).parent.parent / "docs" / "decisions"
INDEX = DECISIONS / "README.md"
FILE = re.compile(r"^(D\d{3}|D188\d*)-[a-z0-9-]+\.md$")
TITLE = re.compile(r"^# (D\d+|D188\d*) — (.+)$")
STATUS = re.compile(r"^Статус: (.+)$", re.MULTILINE)

HEADER = """# Решения

Одно решение — один файл: статус, дата, контекст, решение (слова пользователя), последствия
(где живёт в коде). Только добавление: номера не переиспользуются, отменённое получает статус
«заменено D<n>». Найти `D72` — `ls docs/decisions | grep D072`, по слову — `grep -rl слово
docs/decisions`. Новое решение в ветке — `D188-<slug>.md`, при слиянии — следующий номер
`master` (`CLAUDE.md`, «Параллельные сессии»). Ещё не решённое — `OPEN.md`.

Таблица ниже генерируется: `uv run python scripts/decisions_index.py`, руками не править.

| # | Решение | Статус | Файл |
|---|---|---|---|
"""


def decision_files(folder: Path = DECISIONS) -> list[Path]:
    """Decision files by number; branch files (`D188…`) last."""

    def key(path: Path) -> tuple[int, str]:
        number = path.name.split("-")[0][1:]
        return (int(number) if number.isdigit() else 10**9, path.name)

    return sorted((p for p in folder.iterdir() if FILE.match(p.name)), key=key)


def index_row(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    title = TITLE.match(text.splitlines()[0])
    status = STATUS.search(text)
    if not title or not status:
        raise ValueError(f"{path.name}: no `# D<n> — title` or `Статус:` line")
    return f"| {title[1]} | {title[2]} | {status[1]} | [{path.name}]({path.name}) |"


def render(folder: Path = DECISIONS) -> str:
    return HEADER + "\n".join(index_row(path) for path in decision_files(folder)) + "\n"


def main() -> None:
    INDEX.write_text(render(), encoding="utf-8")
    print(f"{INDEX}: {len(decision_files())} decisions")


if __name__ == "__main__":
    main()
