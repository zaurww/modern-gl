"""Backups of company files: automatic (on close, before a schema update) and manual.

A backup is a full SQLite copy made with the backup API, so it is consistent even while
the company is open. Each company keeps its own folder of backups next to the company
files, the newest KEEP of them:

    Modern GL/Ehtiyat nüsxələri/<Company>/<Company> 2026-10-19 18-05-12.gl

Every backup is checked (PRAGMA quick_check) right after it is written. Restoring first
backs up the current file, so a restore can itself be undone.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

FOLDER = "Ehtiyat nüsxələri"
KEEP = 30
SUFFIX = ".gl"
STAMP = "%Y-%m-%d %H-%M-%S"


class BackupError(LedgerError):
    pass


@dataclass(frozen=True)
class Backup:
    path: Path
    made_at: datetime
    size: int


def folder_for(workspace_folder: Path, company_file: Path) -> Path:
    return Path(workspace_folder) / FOLDER / Path(company_file).stem


def list_backups(folder: Path) -> list[Backup]:
    """Backups in a folder, newest first."""
    result = []
    for path in Path(folder).glob(f"*{SUFFIX}"):
        made = _stamp_of(path)
        if made is not None:
            result.append(Backup(path, made, path.stat().st_size))
    # several backups within one second: the file time orders them
    return sorted(result, key=lambda b: (b.made_at, b.path.stat().st_mtime_ns), reverse=True)


def check(path: Path) -> None:
    """Raise BackupError unless the file is an intact SQLite database."""
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise BackupError(
            tr("файл повреждён: {file} ({error})", file=Path(path).name, error=e)
        ) from e
    if result != "ok":
        raise BackupError(
            tr("файл повреждён: {file} ({error})", file=Path(path).name, error=result)
        )


def copy_to(conn: sqlite3.Connection, target: Path) -> Path:
    """Write a consistent copy of an open database to `target` and check it."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    dst = sqlite3.connect(partial)
    try:
        conn.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")  # a single self-contained file
    finally:
        dst.close()
    try:
        check(partial)
    except BackupError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return target


def make_backup(
    conn: sqlite3.Connection, folder: Path, name: str, note: str = "", keep: int = KEEP
) -> Path:
    """A timestamped backup in `folder`; the oldest beyond `keep` are removed."""
    stamp = datetime.now()
    suffix = f" ({note})" if note else ""
    target = Path(folder) / f"{name} {stamp:{STAMP}}{suffix}{SUFFIX}"
    n = 2
    while target.exists():
        target = Path(folder) / f"{name} {stamp:{STAMP}}{suffix} {n}{SUFFIX}"
        n += 1
    copy_to(conn, target)
    for old in list_backups(folder)[keep:]:
        old.path.unlink(missing_ok=True)
    return target


def make_backup_of_file(path: Path, folder: Path, note: str = "") -> Path:
    """Back up a company file that is not open (e.g. before a schema update)."""
    src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return make_backup(src, folder, Path(path).stem, note)
    finally:
        src.close()


def changed_since_last(conn: sqlite3.Connection, folder: Path) -> bool:
    """Every change is written to the audit trail, so its last id tells whether the
    company changed since the newest backup."""
    latest = list_backups(folder)
    if not latest:
        return True
    current = _last_audit(conn)
    try:
        old = sqlite3.connect(f"file:{latest[0].path.as_posix()}?mode=ro", uri=True)
        try:
            return _last_audit(old) != current
        finally:
            old.close()
    except sqlite3.DatabaseError:
        return True


def restore(backup: Path, company_file: Path, folder: Path) -> Path:
    """Replace a (closed) company file with a backup. The current file is backed up
    first; returns that safety copy."""
    check(backup)
    safety = make_backup_of_file(company_file, folder, tr("до восстановления"))
    src = sqlite3.connect(f"file:{Path(backup).as_posix()}?mode=ro", uri=True)
    try:
        partial = Path(company_file).with_name(Path(company_file).name + ".part")
        copy_to(src, partial)
    finally:
        src.close()
    for extra in ("-wal", "-shm"):
        Path(str(company_file) + extra).unlink(missing_ok=True)
    partial.replace(company_file)
    return safety


def _last_audit(conn: sqlite3.Connection) -> int:
    try:
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM audit_events").fetchone()[0]
    except sqlite3.DatabaseError:
        return -1


def _stamp_of(path: Path) -> datetime | None:
    """The time in a backup's name: '<name> 2026-10-19 18-05-12[ (note)][ n].gl'."""
    parts = path.stem.split(" ")
    for i in range(len(parts) - 1):
        try:
            return datetime.strptime(f"{parts[i]} {parts[i + 1]}", STAMP)
        except ValueError:
            continue
    return None
