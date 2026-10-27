"""A company file on a network or cloud folder (D25, D169): it gets
the classic journal instead of WAL, «Bu gün» says so; and a lock file keeps a second copy
of the program out of a file that is open."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

import pytest

from modern_gl.api import open_company
from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.home_page import HomePage
from modern_gl.desktop.session import Session
from modern_gl.infrastructure import company_file
from modern_gl.infrastructure.company_file import (
    CLOUD,
    LOCAL,
    NETWORK,
    FileInUseError,
    is_network_path,
    lock_path,
    place_of,
)
from modern_gl.infrastructure.db import connect
from tests.helpers.qt import running_app

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="/proc/mounts: the POSIX branch")


@pytest.fixture
def mounts(tmp_path, monkeypatch):
    """/proc/mounts of a machine where `tmp_path/share` is an NFS share."""
    share = tmp_path / "share"
    share.mkdir()
    table = tmp_path / "mounts"
    table.write_text(
        "/dev/sda1 / ext4 rw 0 0\n"
        f"server:/export {share} nfs4 rw 0 0\n"
        f"/dev/sdb1 {share}/usb vfat rw 0 0\n"
        "user@host:/home /mnt/my\\040files fuse.sshfs rw 0 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(company_file, "MOUNTS", table)
    return share


@POSIX
def test_a_network_file_system_is_known_by_its_mount(mounts, tmp_path):
    assert place_of(mounts / "Firma.gl") == NETWORK
    assert place_of(mounts / "usb" / "Firma.gl") == LOCAL  # the longest mount point wins
    assert place_of(tmp_path / "Firma.gl") == LOCAL
    assert place_of("/mnt/my files/Firma.gl") == NETWORK  # a space is \040 in the table
    assert is_network_path(mounts / "Firma.gl") and not is_network_path(tmp_path / "x.gl")


def test_a_cloud_folder_is_known_by_its_name(tmp_path):
    assert place_of(tmp_path / "OneDrive - Firma MMC" / "Documents" / "x.gl") == CLOUD
    assert place_of(tmp_path / "Dropbox" / "x.gl") == CLOUD
    assert place_of(tmp_path / "Google Drive" / "x.gl") == CLOUD
    assert place_of(tmp_path / "Dropboxes" / "x.gl") == LOCAL


def test_windows_shares_and_network_drives(monkeypatch):
    drives = {"Z:\\": company_file.DRIVE_REMOTE, "C:\\": 3}
    monkeypatch.setattr(company_file, "drive_type", lambda root: drives.get(root, 0))
    remote = company_file._windows_remote
    assert remote(r"\\server\share\Firma.gl") and remote("//server/share/Firma.gl")
    assert remote(r"Z:\Mühasibat\Firma.gl")
    assert not remote(r"C:\Users\aynur\Documents\Firma.gl")


@POSIX
def test_a_file_on_a_network_folder_has_no_wal(mounts, tmp_path):
    conn = connect(mounts / "Firma.gl")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    Ledger(conn).create_company("Firma")
    assert not (mounts / "Firma.gl-wal").exists()
    conn.close()
    local = connect(tmp_path / "Yerli.gl")
    assert local.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    local.close()


@pytest.mark.parametrize(("folder", "shown"), [("Dropbox", True), ("Yerli", False)])
def test_bu_gun_says_the_file_is_on_a_shared_folder(qtbot, tmp_path, folder, shown):
    theme.apply(running_app())
    ws = Workspace(tmp_path / folder)
    conn, cid = ws.open(ws.create("Firma"))
    s = Session(conn, Ledger(conn), cid, "Firma", Catalog(conn, cid), notify=lambda m: None)
    s.path = ws.folder / "Firma.gl"
    page = HomePage(s, set())
    qtbot.addWidget(page)
    assert page.place_note.isVisibleTo(page) is shown
    s.read_only = True  # a snapshot in memory: nothing to warn about
    assert s.file_place == LOCAL
    conn.close()


# ---- the lock -------------------------------------------------------------------------


@pytest.fixture
def company(tmp_path):
    ws = Workspace(tmp_path)
    return ws, ws.create("Firma")


def hold(path, pid: int, host: str, user: str = "Aynur") -> None:
    lock_path(path).write_text(json.dumps({"pid": pid, "host": host, "user": user}))


def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_the_lock_lives_while_the_file_is_open(company):
    ws, path = company
    conn, _ = ws.open(path)
    held = json.loads(lock_path(path).read_text())
    assert held["pid"] == os.getpid() and held["host"] == socket.gethostname()
    again, _ = ws.open(path)  # this very program again (another language): one lock
    conn.close()
    assert lock_path(path).exists()
    again.close()
    assert not lock_path(path).exists()


def test_another_copy_of_the_program_is_kept_out(company):
    ws, path = company
    hold(path, 4242, "BUXGALTER-2", "Aynur")
    with pytest.raises(FileInUseError) as e:
        ws.open(path)
    assert "BUXGALTER-2, Aynur" in str(e.value) and "только для просмотра" in str(e.value)
    assert "Firma.gl.lock" in str(e.value)
    conn, _ = ws.view(path)  # viewing (D80) is open to everyone
    conn.close()
    assert lock_path(path).exists()  # not ours: left as it was
    with open_company(path, write=True) as firma:  # a brief write beside it (API)
        assert firma.name == "Firma"


def test_a_living_program_on_this_machine_keeps_its_lock(company):
    ws, path = company
    hold(path, os.getppid(), socket.gethostname())
    with pytest.raises(FileInUseError):
        ws.open(path)


def test_the_lock_of_a_program_that_is_gone_is_taken_over(company):
    ws, path = company
    hold(path, dead_pid(), socket.gethostname())
    conn, _ = ws.open(path)
    assert json.loads(lock_path(path).read_text())["pid"] == os.getpid()
    conn.close()
    assert not lock_path(path).exists()


def test_a_broken_lock_is_taken_over_unless_it_is_being_written(company):
    ws, path = company
    lock_path(path).write_text("")
    with pytest.raises(FileInUseError):  # just made: its program is writing it
        ws.open(path)
    old = lock_path(path).stat().st_mtime - 60
    os.utime(lock_path(path), (old, old))
    conn, _ = ws.open(path)
    conn.close()
    assert not lock_path(path).exists()


def test_a_failed_open_leaves_no_lock(company, monkeypatch):
    ws, path = company

    def broken(_path):
        raise OSError("disk")

    monkeypatch.setattr(ws, "_updated", broken)
    with pytest.raises(OSError, match="disk"):
        ws.open(path)
    assert not lock_path(path).exists()


@POSIX
def test_a_network_file_open_by_its_owner_is_viewed_under_the_engines_locks(mounts):
    ws = Workspace(mounts)
    path = ws.create("Firma")
    owner, _ = ws.open(path)  # the classic journal: no -wal tells it is open, the lock does
    assert not (mounts / "Firma.gl-wal").exists() and lock_path(path).exists()
    viewed, _ = ws.view(path)
    viewed.close()
    owner.close()
    assert sorted(p.name for p in mounts.iterdir() if p.name.startswith("Firma")) == ["Firma.gl"]
