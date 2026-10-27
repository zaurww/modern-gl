"""Shared from test_vat_receipts.py (moved here: other test modules use it too)."""

from __future__ import annotations


def party(v, who: str) -> tuple[int, int]:
    return (v[who], v["Д-1" if who == "Альфа" else "Общий"])
