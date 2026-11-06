"""Names that look alike: a new item against the items there are (D209)."""

from __future__ import annotations

from modern_gl.i18n import fold

SHORTEST = 3  # a shorter fragment is in half of the names
MOST = 5


def _letters(name: str) -> str:
    """A name without case, spaces and signs, Azerbaijani letters as plain ones."""
    return "".join(letter for letter in fold(name) if letter.isalnum())


def similar_choices(name: str, choices: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The (id, label) that look like the name: the same letters, or one has the other
    in it. Those that start alike first; a simple rule the accountant can foresee."""
    wanted = _letters(name)
    if len(wanted) < SHORTEST:
        return []
    found = []
    for choice_id, label in choices:
        other = _letters(label.split("  ", 1)[-1])
        if len(other) >= SHORTEST and (wanted in other or other in wanted):
            alike = other.startswith(wanted) or wanted.startswith(other)
            found.append((not alike, abs(len(other) - len(wanted)), label, choice_id))
    return [(choice_id, label) for *_, label, choice_id in sorted(found)[:MOST]]
