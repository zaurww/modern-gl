"""Backups of company files: automatic (on close, before a schema update) and manual.

A backup is a full SQLite copy made with the backup API, so it is consistent even while
the company is open. Each company keeps its own folder of backups next to the company
files, the newest KEEP of them:

    Modern GL/Ehtiyat nüsxələri/<Company>/<Company> 2026-10-19 18-05-12.gl

Every backup is checked in full (PRAGMA integrity_check) right after it is written: a
copy is page by page, so this is a full check of the company itself after each working
session; a damaged copy is not kept over the good ones. Opening a file runs only the quick
check. Restoring first backs up the current file, so a restore can itself be undone.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

FOLDER = "Ehtiyat nüsxələri"
KEEP = 30
# Beyond the newest KEEP: the last copy of each of this many older schemas — the copy made
# before an update, for a mistake of the update that shows only weeks later (D148)
UPGRADE_KEEP = 3
SUFFIX = ".gl"
STAMP = "%Y-%m-%d %H-%M-%S"


class BackupError(LedgerError):
    """A backup could not be made or restored; the message is for the user."""


@dataclass(frozen=True)
class Backup:
    """One backup file: when it was made (from its name) and its size in bytes."""

    path: Path
    made_at: datetime
    size: int


def folder_for(workspace_folder: Path, company_file: Path) -> Path:
    """Where the backups of a company file are kept: a folder of its own in the workspace."""
    return Path(workspace_folder) / FOLDER / Path(company_file).stem


def list_backups(folder: Path) -> list[Backup]:
    """Backups in a folder, newest first."""
    result: list[Backup] = []
    for path in Path(folder).glob(f"*{SUFFIX}"):
        made = _stamp_of(path)
        if made is not None:
            result.append(Backup(path, made, path.stat().st_size))
    # several backups within one second: the file time orders them
    return sorted(result, key=lambda b: (b.made_at, b.path.stat().st_mtime_ns), reverse=True)


def check(path: Path, full: bool = False) -> None:
    """Raise BackupError unless the file is an intact SQLite database: the quick check
    (pages and records), or in full (integrity_check: indexes match their tables too)."""
    pragma = "integrity_check" if full else "quick_check"
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            found = [r[0] for r in conn.execute(f"PRAGMA {pragma}(5)")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise BackupError(
            tr("файл повреждён: {file} ({error})", file=Path(path).name, error=e)
        ) from e
    if found != ["ok"]:
        raise BackupError(
            tr("файл повреждён: {file} ({error})", file=Path(path).name, error="; ".join(found))
        )


def copy_to(conn: sqlite3.Connection, target: Path) -> Path:
    """Write a consistent copy of an open database to `target` and check it."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        dst = sqlite3.connect(partial)
        try:
            conn.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")  # a single self-contained file
        finally:
            dst.close()
        try:
            check(partial, full=True)
        except BackupError as e:  # the copy is page by page: the source has it too
            raise BackupError(
                tr(
                    "в файле компании найдены повреждения — восстановите его из копии ({error})",
                    error=str(e),
                )
            ) from e
    except BaseException:  # a failed or damaged copy must not be left behind
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return target


def make_backup(
    conn: sqlite3.Connection, folder: Path, name: str, note: str = "", keep: int = KEEP
) -> Path:
    """A timestamped backup in `folder`; the oldest beyond `keep` are removed."""
    target = _new_name(folder, name, note)
    copy_to(conn, target)
    _drop_oldest(folder, keep)
    return target


def _new_name(folder: Path, name: str, note: str) -> Path:
    stamp = datetime.now()
    suffix = f" ({note})" if note else ""
    target = Path(folder) / f"{name} {stamp:{STAMP}}{suffix}{SUFFIX}"
    n = 2
    while target.exists():
        target = Path(folder) / f"{name} {stamp:{STAMP}}{suffix} {n}{SUFFIX}"
        n += 1
    return target


def _drop_oldest(folder: Path, keep: int) -> None:
    copies = list_backups(folder)
    oldest_schema = min((_schema_of(c.path) for c in copies[:keep]), default=0)
    extra = 0
    for old in copies[keep:]:
        schema = _schema_of(old.path)
        if schema < oldest_schema and extra < UPGRADE_KEEP:
            oldest_schema, extra = schema, extra + 1  # the newest copy of an older schema
            continue
        old.path.unlink(missing_ok=True)


def _schema_of(path: Path) -> int:
    """The schema version written in a copy's header (PRAGMA user_version: bytes 60–63)."""
    try:
        with open(path, "rb") as file:
            file.seek(60)
            return int.from_bytes(file.read(4), "big")
    except OSError:
        return 0


def mirror(made: Path, root: Path) -> Path:
    """The same backup in a second folder (a flash drive, a synced cloud folder — D97):
    `<root>/<Company>/<backup name>`, the newest KEEP there too. Raises BackupError when the
    folder cannot be written (the drive is not plugged in…): the first copy stays."""
    target = Path(root) / Path(made).parent.name / Path(made).name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        shutil.copy2(made, partial)
        partial.replace(target)
        _drop_oldest(target.parent, KEEP)
    except OSError as e:
        raise BackupError(
            tr("копия не записана во вторую папку {folder}: {error}", folder=root, error=e)
        ) from e
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
    """Replace a (closed) company file with a backup. The current file is kept first, byte
    for byte and unchecked — it is likely damaged, may not even open, and is what a later
    look at the damage needs; returns that copy."""
    check(backup, full=True)
    Path(folder).mkdir(parents=True, exist_ok=True)
    kept = _new_name(folder, Path(company_file).stem, tr("до восстановления"))
    shutil.copy2(company_file, kept)
    _drop_oldest(folder, KEEP)
    src = sqlite3.connect(f"file:{Path(backup).as_posix()}?mode=ro", uri=True)
    try:
        partial = Path(company_file).with_name(Path(company_file).name + ".part")
        copy_to(src, partial)
    finally:
        src.close()
    for extra in ("-wal", "-shm"):
        Path(str(company_file) + extra).unlink(missing_ok=True)
    partial.replace(company_file)
    return kept


def _last_audit(conn: sqlite3.Connection) -> int:
    """The last change of the company: the company opened or closed (a session of
    «Журнал действий») is no change — else every closing would make a backup."""
    try:
        return conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM audit_events WHERE entity <> 'session'"
        ).fetchone()[0]
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
