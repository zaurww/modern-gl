"""The documents read at the start of every session stay short (D109, docs/CODE_QUALITY.md).

They are read whole each time, so their size is paid in every session. What only grows —
a log of sessions, the old drafts — lives in docs/history and is not read by default.
A document over its limit is shortened first: the done leaves STATUS, the past goes to
docs/history, a detail moves to the module's own document.

`uv run python tests/test_docs_size.py` prints each document's size against its limit.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# characters: what a session reads, not how the lines happen to be wrapped
LIMITS = {
    "README.md": 7_000,
    "CLAUDE.md": 12_000,
    "docs/CONCEPT.md": 6_500,
    "docs/STATUS.md": 12_000,
    "docs/ARCHITECTURE.md": 8_000,
    "docs/ENGINEERING.md": 13_500,
    "docs/CODE_QUALITY.md": 7_000,
}

# a decision is a short record: the choice, the user's words, where it lives in the code;
# the long story goes to the module's document. Older entries stay as they were written.
DECISION_LIMIT = 1_200
SHORT_DECISIONS_FROM = 109


def sizes() -> dict[str, int]:
    return {name: len((ROOT / name).read_text(encoding="utf-8")) for name in LIMITS}


def long_decisions() -> list[str]:
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    found = []
    for line in text.splitlines():
        match = re.match(r"\| D(\d+) \|", line)
        if match and int(match[1]) >= SHORT_DECISIONS_FROM and len(line) > DECISION_LIMIT:
            found.append(f"D{match[1]}: {len(line)} characters, allowed {DECISION_LIMIT}")
    return found


def test_session_documents_stay_short() -> None:
    over = [
        f"{name}: {size} characters, allowed {LIMITS[name]} — shorten it first"
        for name, size in sizes().items()
        if size > LIMITS[name]
    ]
    assert not over, "\n".join(over)


def test_new_decisions_stay_short() -> None:
    assert not long_decisions(), "\n".join(long_decisions())


if __name__ == "__main__":
    for name, size in sizes().items():
        print(f"{size:6} / {LIMITS[name]:<6} {size * 100 // LIMITS[name]:3}%  {name}")
    for line in long_decisions():
        print("!", line)
