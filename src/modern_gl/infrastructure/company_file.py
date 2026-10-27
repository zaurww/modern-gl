"""One company file as a file: what the engine alone reads or does to it, before or beside
the schema — the name inside, the schema version, a consistent copy, one company kept
out of a shared file of the old kind (D18), where it lies (a network or cloud folder) and
the lock that keeps a second copy of the program out (D169). The
folder of such files, their creation and copies are `application/workspace.py`."""

from __future__ import annotations

import getpass
import json
import ntpath
import os
import socket
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, DatabaseError, connect, when_closed


def read_only(path: Path) -> Connection:
    """The file as it is: not migrated, not locked."""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def company_name(path: Path) -> str:
    """Read the company name without migrating or locking the file."""
    conn = read_only(path)
    try:
        row = conn.execute("SELECT name FROM companies ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        raise DatabaseError("no company in file")
    return row[0]


def companies_in(path: Path) -> list[tuple[int, str]]:
    """(id, name) of every company in the file, oldest first: a shared file of the old
    kind holds several."""
    conn = read_only(path)
    try:
        return [tuple(r) for r in conn.execute("SELECT id, name FROM companies ORDER BY id")]
    finally:
        conn.close()


def open_company(path: Path) -> tuple[Connection, int]:
    """Open (and migrate) a company file; returns the connection and the company id."""
    conn = connect(path)
    return conn, first_company(conn, path)


def first_company(conn: Connection, path: Path) -> int:
    """The id of the oldest company in an open file; closes the connection and raises
    DatabaseError when the file has none."""
    row = conn.execute("SELECT id FROM companies ORDER BY id LIMIT 1").fetchone()
    if row is None:
        conn.close()
        raise DatabaseError(f"{path.name}: no company in file")
    return row["id"]


def file_version(path: Path) -> int:
    """The schema version written in the file, without migrating it."""
    conn = read_only(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def sidecars(path: Path) -> tuple[Path, Path]:
    """The -wal and -shm files the engine keeps beside an open file."""
    return path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")


def copy_file(source: Path, target: Path) -> None:
    """A consistent copy of the database file, even of one in use."""
    src = read_only(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def make_self_contained(conn: Connection) -> None:
    """One file and nothing beside it: how a new company file is handed over (D18)."""
    conn.execute("PRAGMA journal_mode = DELETE")


def keep_only(path: Path, company_id: int) -> None:
    """Delete every other company's rows from every table that has company_id. The
    immutability triggers would refuse to delete posted documents, so they are lifted for
    this copy only and put back; references left dangling stop it."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'")
        triggers = triggers.fetchall()
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if r[0] != "companies" and not r[0].startswith("sqlite_")
        ]
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        for trigger, _ in triggers:
            conn.execute(f'DROP TRIGGER "{trigger}"')
        for table in tables:
            columns = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            if "company_id" in columns:
                conn.execute(f'DELETE FROM "{table}" WHERE company_id IS NOT ?', (company_id,))
        conn.execute("DELETE FROM companies WHERE id != ?", (company_id,))
        for _, sql in triggers:
            conn.execute(sql)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            conn.execute("ROLLBACK")
            raise sqlite3.IntegrityError(
                f"{path.name}: broken references {[tuple(r) for r in broken][:5]}"
            )
        conn.execute("COMMIT")
        conn.execute("VACUUM")
    finally:
        conn.close()


# ---- where the file lies (D25: a live .gl is not opened from a network or cloud folder) --

LOCAL, NETWORK, CLOUD = "local", "network", "cloud"
MOUNTS = Path("/proc/mounts")  # POSIX: what is mounted where, with its file system
NETWORK_FS = {
    *("nfs", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afs", "9p", "ncpfs", "coda"),
    *("ceph", "glusterfs", "lustre", "gpfs", "davfs", "sshfs", "webdav"),
}
NETWORK_FUSE = ("sshfs", "rclone", "s3fs", "davfs", "gvfs", "glusterfs", "onedriver", "smb")
# a folder a sync client keeps in step with a cloud: its name in the path
CLOUD_FOLDERS = (
    *("dropbox", "google drive", "googledrive", "my drive", "icloud drive"),
    *("iclouddrive", "mobile documents", "cloudstorage", "yandex.disk", "yandexdisk"),
)
DRIVE_REMOTE = 4  # GetDriveTypeW: a network drive


def place_of(path: Path | str) -> str:
    """LOCAL, NETWORK (a share, a network drive, a network file system) or CLOUD (a folder
    of OneDrive, Dropbox, Google Drive, iCloud, Yandex.Disk)."""
    path = Path(os.path.abspath(path))
    if _in_cloud_folder(path):
        return CLOUD
    if sys.platform == "win32":
        return NETWORK if _windows_remote(str(path)) else LOCAL
    return NETWORK if _remote_file_system(path) else LOCAL


def is_network_path(path: Path | str) -> bool:
    """A network or cloud folder: SQLite's WAL is not for it and two may open the file."""
    return place_of(path) != LOCAL


def _in_cloud_folder(path: Path) -> bool:
    parts = [p.casefold() for p in path.parts]
    return any(p.startswith("onedrive") or p in CLOUD_FOLDERS for p in parts)


def _windows_remote(path: str) -> bool:
    if path.startswith(("\\\\", "//")):  # \\server\share
        return True
    drive = ntpath.splitdrive(path)[0]
    return bool(drive) and drive_type(drive + "\\") == DRIVE_REMOTE


def drive_type(root: str) -> int:
    """GetDriveTypeW of a drive's root («C:\\»); 0 off Windows."""
    if sys.platform == "win32":
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(root)
    return 0


def _remote_file_system(path: Path) -> bool:
    """The file system of the longest mount point the path lies under (/proc/mounts)."""
    try:
        lines = MOUNTS.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False  # no /proc (macOS): taken as local
    best, kind = "", ""
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        point = fields[1].replace("\\040", " ").replace("\\011", "\t")
        inside = path.as_posix() == point or path.as_posix().startswith(point.rstrip("/") + "/")
        if inside and len(point) >= len(best):
            best, kind = point, fields[2].lower()
    fuse = kind.startswith("fuse.") and any(n in kind for n in NETWORK_FUSE)
    return kind in NETWORK_FS or fuse


# ---- one program at a time (D25, D169) ------------------------------


class FileInUseError(LedgerError):
    """Another copy of the program has the company file open."""


@dataclass(frozen=True)
class Holder:
    """Who holds a lock file: the process, its machine and its user."""

    pid: int
    host: str
    user: str

    @staticmethod
    def me() -> Holder:
        """This program."""
        return Holder(os.getpid(), socket.gethostname(), _user())


_HELD: dict[Path, int] = {}  # lock files this process holds → how many opens share each
WRITING = 5.0  # seconds a just-made lock file may stay empty: its maker is writing it


def lock_path(path: Path) -> Path:
    """The lock file of a company file: `<file>.gl.lock` beside it."""
    return path.with_name(path.name + ".lock")


def take_lock(path: Path) -> Path:
    """`<file>.gl.lock` beside the file, with this program's process, machine and user;
    FileInUseError while another living copy of the program holds it. One left by a
    program that is no longer running on this machine is taken over."""
    lock = lock_path(Path(path).absolute())
    for _ in range(3):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = _holder(lock)
            if holder == Holder.me():  # opened again by this very program
                _HELD[lock] = _HELD.get(lock, 0) + 1
                return lock
            if holder is None or _gone(holder):
                lock.unlink(missing_ok=True)
                continue
            raise FileInUseError(_in_use_text(path, lock, holder)) from None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(Holder.me().__dict__, f)
        _HELD[lock] = 1
        return lock
    raise FileInUseError(tr("Файл компании открывается другой программой — повторите"))


def release_lock(lock: Path) -> None:
    """The open that took the lock is closed: the last one removes the file."""
    left = _HELD.get(lock, 0) - 1
    if left > 0:
        _HELD[lock] = left
        return
    _HELD.pop(lock, None)
    if _holder(lock) == Holder.me():  # never another program's
        lock.unlink(missing_ok=True)


def hold_while_open(conn: Connection, lock: Path) -> None:
    """The lock goes with the connection: closing it releases the lock."""
    when_closed(conn, lambda: release_lock(lock))


def _holder(lock: Path) -> Holder | None:
    """Who holds the lock; None — it can be taken over: unreadable, and not just made
    (a program that died while writing it)."""
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return Holder(int(data["pid"]), str(data["host"]), str(data["user"]))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        try:
            fresh = time.time() - lock.stat().st_mtime < WRITING
        except OSError:
            return None
        return Holder(0, "?", "?") if fresh else None


def _gone(holder: Holder) -> bool:
    """The holder's program no longer runs. Known only on this machine: another one's
    lock stays until that program closes the file (or the user removes the lock)."""
    return holder.host == socket.gethostname() and holder.pid > 0 and not _alive(holder.pid)


def _alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill would end the process there
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.GetLastError() == 5  # access denied: it runs, as another user
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # another user's process
    return True


def _user() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError):  # no login name in the environment
        return "?"


def _in_use_text(path: Path, lock: Path, holder: Holder) -> str:
    return tr(
        "Файл компании уже открыт: {host}, {user}. Двоим одновременно работать в одном "
        "файле нельзя — откройте его «только для просмотра» (меню компании → «Открыть "
        "для просмотра…»). Если программа там закрыта, удалите файл «{lock}» рядом с «{file}»",
        host=holder.host,
        user=holder.user,
        lock=lock.name,
        file=Path(path).name,
    )
