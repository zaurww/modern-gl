"""The rows of «Требует внимания» stand in a fixed order — bank, stock, unpaid e-qaimə,
purchases waiting for e-qaimə — whatever order the modules are imported in (the window's
packages once changed it by importing in another order)."""

from __future__ import annotations

import subprocess
import sys

ORDER = ["bank_attention", "negative_stock", "unpaid_invoices", "awaiting_invoices"]
MODULES = [
    "modern_gl.application.bank.statements",
    "modern_gl.reporting.inventory.stock",
    "modern_gl.reporting.invoices",
    "modern_gl.reporting.trade",
]


def order_after_importing(modules: list[str]) -> list[str]:
    code = "\n".join(
        [
            *(f"import {m}" for m in modules),
            "from modern_gl.application.attention import attention_sources",
            "print(' '.join(s.__name__ for s in attention_sources()))",
        ]
    )
    # S603: our own interpreter runs our own code
    shown = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return shown.stdout.split()


def test_the_order_does_not_follow_the_imports():
    assert order_after_importing(MODULES) == ORDER
    assert order_after_importing(MODULES[::-1]) == ORDER
