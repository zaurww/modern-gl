"""The documents read at the start of every session stay short (D109, docs/CODE_QUALITY.md).

They are read whole each time, so their size is paid in every session. What only grows —
a log of sessions, the old drafts — lives in docs/history and is not read by default.
A document over its limit is shortened first: the done leaves STATUS, the past goes to
docs/history, a detail moves to the module's own document.

`uv run python tests/test_docs_size.py` prints each document's size against its limit.
Decisions (docs/decisions) are checked by tests/test_decisions.py.
"""

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
    "docs/DESIGN.md": 8_000,
}


def sizes() -> dict[str, int]:
    return {name: len((ROOT / name).read_text(encoding="utf-8")) for name in LIMITS}


def test_session_documents_stay_short() -> None:
    over = [
        f"{name}: {size} characters, allowed {LIMITS[name]} — shorten it first"
        for name, size in sizes().items()
        if size > LIMITS[name]
    ]
    assert not over, "\n".join(over)


if __name__ == "__main__":
    for name, size in sizes().items():
        print(f"{size:6} / {LIMITS[name]:<6} {size * 100 // LIMITS[name]:3}%  {name}")
