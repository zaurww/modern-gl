"""«Отчёты» (D111): the catalog of every report, its page and the sidebar's pinned ones."""

from modern_gl.desktop.reports_hub.account_prompt import AccountPrompt, ask_account
from modern_gl.desktop.reports_hub.catalog import (
    BY_ID,
    HUB,
    PIN_KEYS,
    REPORTS,
    Report,
    pin_key,
    pinned,
    remember,
    set_pinned,
    shown,
)
from modern_gl.desktop.reports_hub.page import ReportsPage

__all__ = [
    "BY_ID",
    "HUB",
    "PIN_KEYS",
    "REPORTS",
    "AccountPrompt",
    "Report",
    "ReportsPage",
    "ask_account",
    "pin_key",
    "pinned",
    "remember",
    "set_pinned",
    "shown",
]
