"""A failure of the program (D154): the traceback goes to the log and to the «Ошибка»
window; a failure in a worker thread does not take the window down."""

from __future__ import annotations

import logging
import sys
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import crash_dialog, theme
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.reports_page import OsvPage
from modern_gl.i18n import tr
from modern_gl.infrastructure import logs
from modern_gl.infrastructure.db import connect
from tests.helpers.qt import running_app


@pytest.fixture
def shown(monkeypatch):
    """The «Ошибка» window is not opened (it would wait for a click): what it would show."""
    texts: list[str] = []
    monkeypatch.setattr(crash_dialog, "show_crash", texts.append)
    return texts


@pytest.fixture
def log_file(tmp_path):
    path = logs.start(tmp_path)
    yield path
    for handler in list(logging.getLogger().handlers):
        if getattr(handler, "baseFilename", "") == str(path):
            logging.getLogger().removeHandler(handler)
            handler.close()


def test_log_lives_beside_the_companies(log_file, tmp_path):
    assert log_file == tmp_path / "log" / "modern-gl.log"
    logging.getLogger("modern_gl.test").info("hello")
    text = log_file.read_text(encoding="utf-8")
    assert "INFO modern_gl.test: hello" in text
    assert (tmp_path / "log" / "crash.txt").exists()  # faulthandler's file


def test_excepthook_logs_and_shows_the_traceback(log_file, shown, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    crash_dialog.install()
    assert sys.excepthook is crash_dialog.report_crash
    try:
        raise RuntimeError("boom 42")
    except RuntimeError as e:
        sys.excepthook(type(e), e, e.__traceback__)
    assert len(shown) == 1
    assert "RuntimeError: boom 42" in shown[0]
    assert "test_crash.py" in shown[0]
    logged = log_file.read_text(encoding="utf-8")
    assert "ERROR modern_gl: unhandled exception" in logged
    assert "RuntimeError: boom 42" in logged


def test_without_qt_the_traceback_goes_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    crash_dialog.show_crash("Traceback: ZeroDivisionError")
    assert "ZeroDivisionError" in capsys.readouterr().err


def test_crash_dialog_copies_the_traceback(qtbot):
    dialog = crash_dialog.CrashDialog("Traceback (most recent call last):\n  KeyError: 'x'")
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == tr("Ошибка")
    dialog.copy.click()
    assert QApplication.clipboard().text().endswith("KeyError: 'x'")
    assert dialog.copy.text() == tr("Скопировано")


@pytest.fixture
def window(qtbot, tmp_path):
    conn = connect(tmp_path / "ДЕМО ООО.gl")
    create_demo_company(Ledger(conn))
    conn.close()
    theme.apply(running_app())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    assert win.session is not None
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.session.background.wait()
    win.shutdown()


def test_a_failure_in_the_worker_thread_keeps_the_window(window, qtbot, shown, log_file):
    window.session.large = True
    window.show_place(("osv",))
    osv = window.stack.currentWidget()
    assert isinstance(osv, OsvPage)

    def broken(_conn):
        raise KeyError("missing column")

    monkeypatch_fetch = osv.fetch
    osv.fetch = broken  # type: ignore[method-assign]
    osv.refresh()
    window.session.background.wait()
    qtbot.waitUntil(lambda: len(shown) == 1)
    assert "KeyError: 'missing column'" in shown[0]
    assert "background read failed" in log_file.read_text(encoding="utf-8")
    assert window.isVisible() and window.stack.currentWidget() is osv
    osv.fetch = monkeypatch_fetch  # type: ignore[method-assign]
    osv.refresh()  # the page goes on reading
    qtbot.waitUntil(lambda: bool(osv.model.rows))
