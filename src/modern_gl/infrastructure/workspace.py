"""A folder of company files: one SQLite file per company.

A company is the unit you hand over: give a colleague its file and they add it to
their folder. Deleting moves the file to a "Silinmiş" subfolder instead of erasing it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modern_gl.application.ledger import Ledger
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.chart_csv import DEFAULT_TEMPLATE, apply_chart_template
from modern_gl.infrastructure.db import connect, latest_version

SUFFIX = ".gl"
TRASH = "Silinmiş"
# Every table that belongs to a company (used when splitting an old shared file).
COMPANY_TABLES = (
    "audit_events",
    "entry_template_lines",
    "entry_templates",
    "postings",
    "documents",
    "accounts",
    "subconto_values",
    "currency_rates",
    "currencies",
    "subconto_kinds",
    "layers",
)


@dataclass(frozen=True)
class CompanyFile:
    path: Path
    name: str


def company_name(path: Path) -> str:
    """Read the company name without migrating or locking the file."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT name FROM companies ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        raise sqlite3.DatabaseError("no company in file")
    return row[0]


def open_company(path: Path) -> tuple[sqlite3.Connection, int]:
    """Open (and migrate) a company file; returns the connection and the company id."""
    conn = connect(path)
    row = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
    if row is None:
        conn.close()
        raise sqlite3.DatabaseError(f"{path.name}: no company in file")
    return conn, row["id"]


class Workspace:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def companies(self) -> list[CompanyFile]:
        result = []
        for path in self.folder.glob(f"*{SUFFIX}"):
            try:
                result.append(CompanyFile(path, company_name(path)))
            except sqlite3.DatabaseError:
                continue  # not a company file (or damaged): never fail the whole list
        return sorted(result, key=lambda c: sort_key(c.name))

    def create(self, name: str, chart: str | None = DEFAULT_TEMPLATE) -> Path:
        """New company file with the chart template (in the interface language)."""
        path = self._free_path(name)
        conn = connect(path)
        try:
            ledger = Ledger(conn)
            company_id = ledger.create_company(name)
            if chart:
                apply_chart_template(ledger, company_id, chart)
        finally:
            conn.close()
        return path

    # ---- backups ---------------------------------------------------------------------

    def backup_folder(self, company_file: Path) -> Path:
        return backup.folder_for(self.folder, company_file)

    def open(self, path: Path) -> tuple[sqlite3.Connection, int]:
        """Open a company file; a file about to get a newer schema is backed up first,
        and a damaged file is refused (backup.BackupError) so it can be restored."""
        path = Path(path)
        backup.check(path)
        if _file_version(path) < latest_version():
            backup.make_backup_of_file(path, self.backup_folder(path), tr("до обновления"))
        return open_company(path)

    def auto_backup(self, conn: sqlite3.Connection, company_file: Path) -> Path | None:
        """The backup made when a company is closed — only if it changed since the last one."""
        folder = self.backup_folder(company_file)
        if not backup.changed_since_last(conn, folder):
            return None
        return backup.make_backup(conn, folder, Path(company_file).stem)

    def backups(self, company_file: Path) -> list[backup.Backup]:
        return backup.list_backups(self.backup_folder(company_file))

    def restore(self, backup_file: Path, company_file: Path) -> Path:
        """Put a backup in place of a closed company file (the current one is kept as a
        backup too). Returns that safety copy."""
        return backup.restore(backup_file, company_file, self.backup_folder(company_file))

    def delete(self, path: Path) -> Path:
        """Move a company file to the Silinmiş subfolder; returns where it went."""
        trash = self.folder / TRASH
        trash.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        target = trash / f"{path.stem} ({stamp}){SUFFIX}"
        path.replace(target)
        for extra in ("-wal", "-shm"):  # leftovers of an unclean shutdown travel along
            side = path.with_name(path.name + extra)
            if side.exists():
                side.replace(target.with_name(target.name + extra))
        return target

    def add_file(self, source: Path) -> list[Path]:
        """Copy a company file into the folder. An old shared file holding several
        companies is split: each company gets its own file. Source is left untouched."""
        src = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
        try:
            companies = src.execute("SELECT id, name FROM companies ORDER BY id").fetchall()
        finally:
            src.close()
        return [self._extract(Path(source), cid, name) for cid, name in companies]

    # ---- internals -------------------------------------------------------------------

    def _extract(self, source: Path, company_id: int, name: str) -> Path:
        target = self._free_path(name)
        src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(target, isolation_level=None)
        try:
            src.backup(dst)  # consistent copy even of a file in use
            # Remove other companies. Immutability triggers would refuse to delete posted
            # documents, so they are lifted for this copy only and restored right after.
            triggers = dst.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
            dst.execute("PRAGMA foreign_keys = OFF")
            dst.execute("BEGIN")
            for trigger, _ in triggers:
                dst.execute(f'DROP TRIGGER "{trigger}"')
            existing = {
                r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table in COMPANY_TABLES:
                if table in existing:  # an older file may not have the newer tables yet
                    dst.execute(f"DELETE FROM {table} WHERE company_id IS NOT ?", (company_id,))
            dst.execute("DELETE FROM companies WHERE id != ?", (company_id,))
            for _, sql in triggers:
                dst.execute(sql)
            dst.execute("COMMIT")
            dst.execute("VACUUM")
        finally:
            src.close()
            dst.close()
        connect(target).close()  # bring an older file up to the current schema
        return target

    def new_path(self, name: str) -> Path:
        """A not-yet-existing file path for a company with this name."""
        return self._free_path(name)

    def _free_path(self, name: str) -> Path:
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
        stem = re.sub(r"\s+", " ", stem).strip(" .") or "company"
        path = self.folder / f"{stem}{SUFFIX}"
        n = 2
        while path.exists():
            path = self.folder / f"{stem} ({n}){SUFFIX}"
            n += 1
        return path


def _file_version(path: Path) -> int:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
