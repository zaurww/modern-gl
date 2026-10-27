"""A folder of company files: one SQLite file per company.

A company is the unit you hand over: give a colleague its file and they add it to
their folder. Deleting moves the file to a "Silinmiş" subfolder instead of erasing it.
A company saved elsewhere («Save as») is remembered by its path and listed too.
What the engine does to a file (its name inside, a copy, one company kept out of a
shared file) — `infrastructure/company_file.py`.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from modern_gl.application.chart_csv import DEFAULT_TEMPLATE, apply_chart_template
from modern_gl.application.document_language import open_in
from modern_gl.application.ledger import Ledger
from modern_gl.domain.company import FULL
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import DEFAULT as DEFAULT_LANGUAGE
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.company_file import (
    companies_in,
    company_name,
    copy_file,
    file_version,
    first_company,
    hold_while_open,
    keep_only,
    make_self_contained,
    open_company,
    release_lock,
    sidecars,
    take_lock,
)
from modern_gl.infrastructure.db import (
    Connection,
    DatabaseError,
    connect,
    latest_version,
    open_snapshot,
)

SUFFIX = ".gl"
TRASH = "Silinmiş"


class UpgradeError(LedgerError):
    """A company file could not be brought up to this program's schema; it is unchanged."""


@dataclass(frozen=True)
class CompanyFile:
    path: Path
    name: str


class Workspace:
    def __init__(
        self, folder: Path, files: Iterable[Path | str] = (), mirror: Path | str | None = None
    ) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        # a second folder every backup is copied to (D97); the caller stores it
        self.mirror: Path | None = Path(mirror) if mirror else None
        # company files kept outside the folder; the caller stores this list
        self.files: list[Path] = []
        for file in files:
            self.remember(Path(file))

    def companies(self) -> list[CompanyFile]:
        result = []
        # a remembered file that is missing (a flash drive not plugged in) is just skipped
        outside = [f for f in self.files if f.is_file()]
        seen: set[Path] = set()
        for path in [*self.folder.glob(f"*{SUFFIX}"), *outside]:
            if path.resolve() in seen:  # the folder may have changed since it was remembered
                continue
            seen.add(path.resolve())
            try:
                result.append(CompanyFile(path, company_name(path)))
            except DatabaseError:
                continue  # not a company file (or damaged): never fail the whole list
        return sorted(result, key=lambda c: sort_key(c.name))

    def create(
        self,
        name: str,
        chart: str | None = DEFAULT_TEMPLATE,
        path: Path | None = None,
        mode: str = FULL,
        tax_id: str | None = None,
    ) -> Path:
        """New company file with the chart template (in the interface language); in the
        folder unless `path` is given (then it is remembered). The file is built aside and
        put in place only when complete, so a failure leaves nothing half-made. `mode`:
        how it is kept (D90) — a warehouse only still gets the chart, unseen; `tax_id` —
        its VÖEN (D113)."""
        path = self._free_path(name) if path is None else Path(path)
        partial = path.with_name(path.name + ".part")
        for leftover in (partial, *sidecars(partial)):
            leftover.unlink(missing_ok=True)
        try:
            conn = connect(partial)
            try:
                ledger = Ledger(conn)
                company_id = ledger.create_company(name)
                ledger.set_document_language(company_id, DEFAULT_LANGUAGE)  # D152
                if chart:
                    apply_chart_template(ledger, company_id, chart)
                if mode != FULL:
                    ledger.set_company_mode(company_id, mode)
                if tax_id:
                    ledger.set_company_tax_id(company_id, tax_id)
                make_self_contained(conn)
            finally:
                conn.close()
            for side in sidecars(path):  # leftovers of a file being replaced are not ours
                side.unlink(missing_ok=True)
            partial.replace(path)
        except BaseException:
            for leftover in (partial, *sidecars(partial)):
                leftover.unlink(missing_ok=True)
            raise
        self.remember(path)
        return path

    def remember(self, path: Path) -> None:
        """Keep listing a company file that lies outside the folder."""
        path = Path(path).absolute()
        if path.parent.resolve() != self.folder.resolve() and not any(
            _same(path, f) for f in self.files
        ):
            self.files.append(path)

    def forget(self, path: Path) -> None:
        self.files = [f for f in self.files if not _same(f, Path(path))]

    def save_as(self, conn: Connection, current: Path, target: Path, name: str) -> Path:
        """Copy the open company to `target` under a new company name; the current file
        stays as it was. Afterwards the company is worked on in `target`."""
        target = Path(target)
        if _same(target, Path(current)):
            raise backup.BackupError(tr("Выберите другой файл: этот уже открыт"))
        for side in sidecars(target):  # leftovers of the file being replaced are not ours
            side.unlink(missing_ok=True)
        backup.copy_to(conn, target)
        copy, company_id = open_company(target)
        try:
            Ledger(copy).rename_company(company_id, name)
        finally:
            copy.close()
        self.remember(target)
        return target

    # ---- backups ---------------------------------------------------------------------

    def backup_folder(self, company_file: Path) -> Path:
        return backup.folder_for(self.folder, company_file)

    def open(self, path: Path, *, lock: bool = True) -> tuple[Connection, int]:
        """Open a company file; a file about to get a newer schema is backed up first
        (a failed update: UpgradeError, the file as it was), a file of a newer program is
        refused untouched (NewerFileError), and a damaged file is refused
        (backup.BackupError) so it can be restored. Its documents are written in its
        language of documents from now on (D152). `lock`: the program's own open — a file
        another copy of the program holds is refused (FileInUseError), and holds it until
        closed (D-new-network-folder-lock); a brief write beside it (AI drafts, the API)
        takes no lock."""
        path = Path(path)
        held = take_lock(path) if lock else None
        try:
            conn, company_id = self._updated(path)
        except BaseException:
            if held is not None:
                release_lock(held)
            raise
        if held is not None:
            hold_while_open(conn, held)
        try:
            open_in(conn, company_id, write=True)
        except BaseException:
            conn.close()
            raise
        return conn, company_id

    def _updated(self, path: Path) -> tuple[Connection, int]:
        backup.check(path)
        if file_version(path) >= latest_version():  # a newer file: NewerFileError
            return open_company(path)
        made = backup.make_backup_of_file(path, self.backup_folder(path), tr("до обновления"))
        try:
            return open_company(path)
        except DatabaseError as e:  # the update is one transaction: nothing was written
            raise UpgradeError(
                tr(
                    "Файл «{file}» не удалось обновить для этой версии программы: {error}. "
                    "Файл не изменён, его копия до обновления — {copy}",
                    file=path.name,
                    error=e,
                    copy=made,
                )
            ) from e

    def view(self, path: Path) -> tuple[Connection, int]:
        """A company file for viewing only (D80): a snapshot in memory; the file is not
        changed, updated or backed up. A damaged file is refused (backup.BackupError)."""
        path = Path(path)
        try:
            conn = open_snapshot(path)
        except DatabaseError as e:
            raise backup.BackupError(
                tr("файл повреждён: {file} ({error})", file=path.name, error=e)
            ) from e
        company_id = first_company(conn, path)
        open_in(conn, company_id, write=False)
        return conn, company_id

    def auto_backup(self, conn: Connection, company_file: Path) -> Path | None:
        """The backup made when a company is closed — only if it changed since the last one."""
        if not backup.changed_since_last(conn, self.backup_folder(company_file)):
            return None
        return self.backup_now(conn, company_file)

    def backup_now(self, conn: Connection, company_file: Path) -> Path:
        """A backup in the company's folder, and in the second folder when there is one
        (BackupError if that one failed: the first copy is made all the same)."""
        made = backup.make_backup(conn, self.backup_folder(company_file), Path(company_file).stem)
        if self.mirror is not None:
            backup.mirror(made, self.mirror)
        return made

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
        shutil.move(path, target)  # a file saved elsewhere may be on another drive
        for extra in ("-wal", "-shm"):  # leftovers of an unclean shutdown travel along
            side = path.with_name(path.name + extra)
            if side.exists():
                shutil.move(side, target.with_name(target.name + extra))
        self.forget(path)
        return target

    def add_file(self, source: Path) -> list[Path]:
        """Add a company file where it lies: it is remembered and opened in place. An old
        shared file holding several companies is split into the folder, one file per
        company, and is itself left untouched."""
        source = Path(source).absolute()
        companies = companies_in(source)
        if len(companies) == 1:
            self.remember(source)
            return [source]
        return [self._extract(source, cid, name) for cid, name in companies]

    # ---- internals -------------------------------------------------------------------

    def _extract(self, source: Path, company_id: int, name: str) -> Path:
        """One company of a shared file into a file of its own. The copy is made in a
        `.part` file and brought up to the current schema first, so every table is there
        to be cleared of the other companies; it takes the company's name only once whole."""
        target = self._free_path(name)
        partial = target.with_name(target.name + ".part")
        for leftover in (partial, *sidecars(partial)):
            leftover.unlink(missing_ok=True)
        try:
            copy_file(source, partial)  # consistent copy even of a file in use
            connect(partial).close()  # an older file: the current schema, every table
            keep_only(partial, company_id)
            partial.replace(target)
        except BaseException:
            for leftover in (partial, *sidecars(partial)):
                leftover.unlink(missing_ok=True)
            raise
        return target

    def new_path(self, name: str, folder: Path | None = None) -> Path:
        """A not-yet-existing file path for a company with this name."""
        return self._free_path(name, folder)

    def _free_path(self, name: str, folder: Path | None = None) -> Path:
        folder = self.folder if folder is None else Path(folder)
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
        stem = re.sub(r"\s+", " ", stem).strip(" .") or "company"
        path = folder / f"{stem}{SUFFIX}"
        n = 2
        while path.exists():
            path = folder / f"{stem} ({n}){SUFFIX}"
            n += 1
        return path


def _same(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()
