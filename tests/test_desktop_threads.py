"""Threads of the window (D93, debt 6): what a worker runs touches no widget, and a portal
job outlives the window that started it without taking the program down."""

from __future__ import annotations

import ast
import gc
import threading
from pathlib import Path

from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from modern_gl.desktop import portal_worker

DESKTOP = Path(__file__).parent.parent / "src" / "modern_gl" / "desktop"
# the page's widgets: read on the window's thread only, before the job is handed over
WIDGETS = {"table", "model", "header", "period", "view", "tree"}


def _touches(node: ast.AST) -> list[int]:
    return [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute)
        and n.attr in WIDGETS
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    ]


def _jobs(method: ast.FunctionDef) -> list[ast.AST]:
    """What of `method` runs in a worker: fetch() itself, what job() returns, and what is
    handed to `….read(owner, job, …)`."""
    if method.name == "fetch":
        return [method]
    nested = {
        n.name: n for n in ast.walk(method) if isinstance(n, ast.FunctionDef) and n is not method
    }
    if method.name == "job":
        return [*nested.values(), *(n for n in ast.walk(method) if isinstance(n, ast.Lambda))]
    jobs: list[ast.AST] = []
    for call in ast.walk(method):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "read"
            and len(call.args) >= 2
        ):
            job = call.args[1]
            if isinstance(job, ast.Lambda):
                jobs.append(job)
            elif isinstance(job, ast.Name) and job.id in nested:
                jobs.append(nested[job.id])
    return jobs


def widgets_read_in_workers() -> list[str]:
    found = []
    for path in DESKTOP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for method in (m for m in cls.body if isinstance(m, ast.FunctionDef)):
                for job in _jobs(method):
                    where = f"{path.relative_to(DESKTOP)}:{cls.name}.{method.name}"
                    found += [f"{where}:{line}" for line in _touches(job)]
    return found


def test_a_worker_reads_no_widget():
    assert widgets_read_in_workers() == []


def test_the_check_sees_a_widget_read_in_a_job():
    source = """
class Page:
    def refresh(self):
        def read(conn):
            return conn.execute(self.period.text())
        self.s.read(self, read, self.present, print)

    def fetch(self, conn):
        return self.table.currentIndex()
"""
    cls = ast.parse(source).body[0]
    assert isinstance(cls, ast.ClassDef)
    lines = [
        line
        for m in cls.body
        if isinstance(m, ast.FunctionDef)
        for j in _jobs(m)
        for line in _touches(j)
    ]
    assert lines == [5, 9]


def test_a_portal_job_outlives_its_window(qtbot):
    """The window closes while the portal still answers: nothing reaches it, no crash."""
    window = QWidget()
    release = threading.Event()
    heard: list = []
    portal_worker.run_on_portal(
        window,
        lambda progress: release.wait(5) and "answer",
        heard.append,
        heard.append,
        heard.append,
    )
    window.deleteLater()
    qtbot.wait(20)  # the window is gone, its thread is not
    release.set()
    portal_worker.wait_all()
    qtbot.wait(50)
    assert heard == []


def test_a_portal_job_says_how_it_went(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    heard: list = []
    run = portal_worker.run_on_portal(
        window, lambda progress: (progress("1 из 1"), 42)[1], heard.append, heard.append, print
    )
    qtbot.waitUntil(lambda: run.done)
    assert heard == ["1 из 1", 42]


def test_a_finished_job_is_freed_on_the_window_thread_only(qtbot):
    """The loader is deleted after its thread is joined, by the window's thread — not by
    a deleteLater inside the worker while Python still holds the wrapper (a rare crash
    of CI's xdist worker in test_currency_ui). Many jobs in a row leave nothing behind."""
    window = QWidget()
    qtbot.addWidget(window)
    runs = [
        portal_worker.run_on_portal(window, lambda progress, n=n: n, print, print, print)
        for n in range(40)
    ]
    loaders = [loader for _thread, loader in portal_worker._RUNNING.values()]
    qtbot.waitUntil(lambda: all(r.done for r in runs))
    gc.collect()  # the old code died here: the wrapper freed under a worker's deleteLater
    portal_worker.wait_all()
    assert portal_worker._RUNNING == {}
    assert not any(isValid(loader) for loader in loaders)
    qtbot.wait(50)  # the queued `_finished` of each thread finds nothing left to do
