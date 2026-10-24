"""Which documents bring goods in (`INCOMING_TYPES`) — one list for Python and for SQL
(«Долг» 14): a new incoming type is added once and every query sees it."""

from __future__ import annotations

import re
from pathlib import Path

from modern_gl.application.inventory.model import INCOMING_SQL, INCOMING_TYPES

SRC = Path(__file__).parent.parent / "src" / "modern_gl"


def test_the_sql_list_is_the_python_set():
    assert set(re.findall(r"'(\w+)'", INCOMING_SQL)) == INCOMING_TYPES


def test_no_query_spells_the_list_by_hand():
    bad = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if "'opening', 'receipt', 'incoming'" in p.read_text(encoding="utf-8")
    ]
    assert not bad, f"список входящих документов вручную: {bad} — INCOMING_SQL"
