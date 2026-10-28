"""The rates a statement in a currency needs (D146): the days of its lines without a
rate of the Central Bank — a conversion or a payment of such a day cannot be posted. Told
above the lines; «Загрузить курсы ЦБА» fetches them off the window's thread, then the
window shows the lines again."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from modern_gl.application.bank.files import BankFile
from modern_gl.application.currencies import days_without_rate
from modern_gl.desktop.cbar_rates import load_rates
from modern_gl.desktop.import_window import say
from modern_gl.desktop.portal_worker import PortalRun
from modern_gl.desktop.session import Session
from modern_gl.i18n import tr


class FileRates:
    def __init__(
        self,
        session: Session,
        files: Sequence[BankFile],
        note: QLabel,
        load_button: QPushButton,
        loaded: Callable[[], None],
        parent: QWidget,
    ) -> None:
        self.s, self.files, self.note, self.button = session, files, note, load_button
        self.loaded, self.parent = loaded, parent
        self.missing: dict[str, list[str]] = {}
        self.run: PortalRun | None = None
        load_button.clicked.connect(self.load)

    def show(self) -> None:
        """«Нет курса ЦБА: EUR — 17 дней»; nothing missing — nothing shown."""
        needs = [(f.currency, line.day) for f in self.files for line in f.lines]
        self.missing = days_without_rate(self.s.conn, self.s.company_id, needs)
        parts = [
            tr("{code} — дней: {n}", code=code, n=len(days)) for code, days in self.missing.items()
        ]
        text = (
            tr(
                "Нет курса ЦБА: {what}. Без курса строки этих дней не проводятся.",
                what=", ".join(parts),
            )
            if parts
            else ""
        )
        say(self.note, text, "warning")
        self.button.setVisible(bool(parts) and not self.s.read_only)

    def load(self) -> None:
        days = sorted({day for days in self.missing.values() for day in days})
        if not days or self.run is not None:
            return
        self.button.setEnabled(False)
        self.run = load_rates(
            self.s,
            self.parent,
            days,
            lambda text: say(self.note, text, "warning"),
            self._loaded,
            self._failed,
        )

    def _loaded(self, _days: int) -> None:
        self.run = None
        self.button.setEnabled(True)
        self.loaded()

    def _failed(self, message: str) -> None:
        self.run = None
        self.button.setEnabled(True)
        say(self.note, message, "warning")
