"""Backups thinned by time (D222): the newest few, then the last copy of each
day for a month and of each month for a year — a mistake seen weeks later still has a copy
from before it; and a copy every hour of work, not only when the company is closed."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from modern_gl.application.ledger import PostingInput
from modern_gl.application.workspace import Workspace
from modern_gl.infrastructure import backup
from tests.helpers.backup import company, documents

# newest first; True — kept with the newest 2, 30 days and 12 months (counted by hand)
COPIES = [
    ("2026-11-25 18-00-00", True),  # the newest two
    ("2026-11-25 12-00-00", True),
    ("2026-11-25 09-00-00", False),  # the 25th has a later copy
    ("2026-11-24 17-00-00", True),  # the last of the 24th
    ("2026-11-24 10-00-00", False),
    ("2026-10-27 17-00-00", True),  # 29 days before the newest: still a day of its own
    ("2026-10-26 17-00-00", False),  # 30 days: only the month counts, October has a later one
    ("2026-10-03 09-00-00", False),
    ("2026-09-30 18-00-00", True),  # the last of September
    ("2026-09-12 08-00-00", False),
    ("2025-12-31 10-00-00", True),  # 11 months back: the last of that December
    ("2025-11-30 10-00-00", False),  # 12 months back: beyond the year
    ("2025-11-02 10-00-00", False),
]


def test_days_and_months_keep_their_last_copy(tmp_path):
    assert (backup.DAYS, backup.MONTHS) == (30, 12)
    for stamp, _ in COPIES:
        (tmp_path / f"Firma {stamp}.gl").write_bytes(bytes(100))
    backup.thin(tmp_path, keep=2)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == sorted(f"Firma {stamp}.gl" for stamp, kept in COPIES if kept)


def test_the_second_folder_is_thinned_the_same_way(tmp_path):
    ws = Workspace(tmp_path / "data", mirror=tmp_path / "cloud")
    path, conn, *_ = company(ws)
    cloud = tmp_path / "cloud" / "Firma"
    cloud.mkdir(parents=True)
    day = datetime.now() - timedelta(days=40)  # another month, within the year: its last stays
    old = [f"{day:%Y-%m-%d} 18-00-00", f"{day:%Y-%m-%d} 09-00-00"]
    for stamp in old:
        (cloud / f"Firma {stamp}.gl").write_bytes(bytes(100))
    for _ in range(backup.KEEP):
        ws.backup_now(conn, path)
    conn.close()
    names = {p.name for p in cloud.iterdir()}
    assert f"Firma {old[0]}.gl" in names and f"Firma {old[1]}.gl" not in names
    assert len(names) == backup.KEEP + 1


def test_a_copy_while_the_company_stays_open(tmp_path):
    """Made by a connection of its own (off the window's thread), with all that is saved;
    nothing new since the last copy — no copy."""
    ws = Workspace(tmp_path / "data", mirror=tmp_path / "cloud")
    path, conn, ledger, cid, (a, b) = company(ws)
    ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    made = ws.timed_backup(path)
    assert made is not None and documents(made) == 1
    assert documents(tmp_path / "cloud" / "Firma" / made.name) == 1
    assert ws.timed_backup(path) is None
    ledger.post_new(cid, "2026-03-02", [PostingInput(a, b, "200")])
    second = ws.timed_backup(path)
    assert second is not None and documents(second) == 2
    assert ws.auto_backup(conn, path) is None  # closing right after: nothing new to copy
    conn.close()


def test_the_window_copies_every_hour_and_says_a_failure_once(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.desktop.main_window import MainWindow
    from modern_gl.desktop.timed_backup import EVERY

    said: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: said.append(text))
    ws = Workspace(tmp_path / "data")
    path, conn, _ledger, cid, (a, b) = company(ws)
    conn.close()
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.start()
    timed = win.company.timed
    assert timed.timer.isActive() and timed.timer.interval() == EVERY == 60 * 60 * 1000
    assert win.ledger is not None
    win.ledger.post_new(cid, "2026-03-01", [PostingInput(a, b, "100")])
    timed.tick()
    timed.wait()
    [made] = ws.backups(path)
    assert documents(made.path) == 1

    blocked = tmp_path / "not a folder"
    blocked.write_text("a file where the folder should be")
    ws.mirror = Path(blocked)
    for day in ("02", "03"):  # two hours, the flash drive still out: said once
        win.ledger.post_new(cid, f"2026-03-{day}", [PostingInput(a, b, "50")])
        timed.tick()
        timed.wait()
        qtbot.wait(50)  # what the job said arrives through the event loop
    assert len(said) == 1
    assert "во вторую папку" in said[0] or "ikinci qovluğa" in said[0]
    ws.mirror = None
    win.shutdown()
    assert not timed.timer.isActive()
