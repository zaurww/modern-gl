"""The program's log: a file beside the company files, rotated so it never grows large.

`start(folder)` writes `folder/log/modern-gl.log` (time, level, module, message; ~1 MB,
three older copies kept) and points the interpreter's fault handler at `log/crash.txt`,
where a hard crash (a segfault in a library) leaves the Python stack. What the program
sends to a portal — tokens, passwords, request bodies — is never logged (ENGINEERING 2.6)."""

from __future__ import annotations

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "modern-gl.log"
CRASH_NAME = "crash.txt"
MAX_BYTES = 1_000_000
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_crash_file = None  # kept open: faulthandler writes to its descriptor


def start(folder: Path, level: int = logging.INFO) -> Path:
    """Log into `folder/log/`; returns the log file's path. A folder that cannot be written
    (a read-only share) leaves the program without a log file, not without the program."""
    global _crash_file
    log_dir = Path(folder) / "log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / LOG_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except OSError:
        logging.getLogger(__name__).warning("no log folder at %s", log_dir)
        return log_dir / LOG_NAME
    handler.setFormatter(logging.Formatter(FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    for old in [h for h in root.handlers if isinstance(h, RotatingFileHandler)]:
        root.removeHandler(old)  # started twice (tests): one file, one handler
        old.close()
    root.addHandler(handler)
    if _crash_file is None:
        try:
            _crash_file = (log_dir / CRASH_NAME).open("a", encoding="utf-8")
            faulthandler.enable(_crash_file)
        except OSError:
            _crash_file = None
    return log_dir / LOG_NAME
