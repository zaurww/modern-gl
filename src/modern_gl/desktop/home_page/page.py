"""«Bu gün» (D86): one narrow column, lists over thin lines — «Требует внимания»,
«Деньги», «Курсы», «Резервная копия» (D97). Quiet: no cards, no colored icons; color
only for a negative sum."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from modern_gl.application.attention import POST_DRAFTS, Attention
from modern_gl.desktop.home_page.rows import Line, Section
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import PageHeader, button, hide_when_viewing, money, ru_date
from modern_gl.domain.currency import format_rate
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.company_file import LOCAL
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.overview import (
    DayRate,
    Money,
    attention,
    rates,
)
from modern_gl.reporting.overview import money as money_rows


@dataclass(frozen=True)
class Overview:
    """What «Bu gün» read for a day; `money` None — a warehouse-only company (D90)."""

    day: str
    attention: list[Attention]
    money: list[Money] | None
    rates: list[DayRate]


COLUMN = 640  # one narrow column: read top to bottom, not across a wide screen


class HomePage(PageWidget):
    key = ("home",)
    open_place = Signal(object)  # a sidebar place: («journal»,), («bank»,)…
    open_backups = Signal()  # «Резервные копии» of the company menu (D97)

    def __init__(self, session: Session, places: set) -> None:
        """`places` — the sidebar's places of this company: a row opens only one of them."""
        super().__init__()
        self.places = places
        self.setObjectName("page")
        self.s = session
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        sheet = QWidget()
        sheet.setObjectName("page")
        scroll.setWidget(sheet)
        row = QHBoxLayout(sheet)
        row.setContentsMargins(40, 30, 40, 24)
        row.addStretch(1)
        self.column = QVBoxLayout()
        self.column.setSpacing(0)
        column = QWidget()
        column.setMaximumWidth(COLUMN)
        column.setMinimumWidth(min(COLUMN, 420))
        column.setLayout(self.column)
        row.addWidget(column, 4)
        row.addStretch(1)
        self.header = PageHeader(tr("Сегодня"))
        self.column.addWidget(self.header)
        self.column.addWidget(self._place_note())
        self.body = QVBoxLayout()
        self.body.setSpacing(0)
        self.column.addLayout(self.body)
        self.column.addStretch(1)
        self.sections: list[Section] = []
        self.refresh()

    def title(self) -> str:
        return tr("Сегодня")

    def _place_note(self) -> QLabel:
        """An amber plate, no window (D86): the file lies on a network or cloud folder."""
        self.place_note = QLabel(
            tr(
                "Файл открыт с сетевой или облачной папки — работает медленнее, двоим "
                "одновременно открывать нельзя"
            )
        )
        self.place_note.setObjectName("warning")
        self.place_note.setWordWrap(True)
        self.place_note.setVisible(self.s.file_place != LOCAL)
        return self.place_note

    def activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """The three lists read (in the background for a large company) and shown."""
        day = iso_date(self.s.working_date)
        self.header.subtitle.setText(f"{ru_date(day)}   ·   {self.s.company_name}")
        cid, books = self.s.company_id, not self.s.stock_only  # no books: no money (D90)

        def read(conn: Connection) -> Overview:
            return Overview(
                day,
                attention(conn, cid, day),
                money_rows(conn, cid, day) if books else None,
                rates(conn, cid, day),
            )

        self.s.read(self, read, self._present, lambda e: self.s.notify(str(e)))

    def _present(self, read: Overview) -> None:
        for section in self.sections:  # hidden at once: deleteLater waits for the loop
            self.body.removeWidget(section)
            section.hide()
            section.deleteLater()
        self.sections = [self._attention(read.attention)]
        if read.money is not None:
            self.sections.append(self._money(read.money))
        self.sections.append(self._rates(read.rates))
        if not self.s.read_only:  # viewing a snapshot: its file's copies are not ours
            self.sections.append(self._backup())
        for section in self.sections:
            self.body.addWidget(section)

    # ---- the three lists -------------------------------------------------------------

    def _attention(self, found: list[Attention]) -> Section:
        section = Section(tr("Требует внимания"))
        rows = [r for r in found if r.place in self.places]
        for row in rows:
            figure = money(row.amount) if row.amount else str(row.count)
            note = str(row.count) if row.amount else ""
            line = section.add(Line(row.text, note, figure)).opens(self._opener(row))
            if row.action == POST_DRAFTS:
                post = button(tr("Провести все"), "flat")
                post.clicked.connect(lambda _=False: self.post_drafts())
                hide_when_viewing(self.s.read_only, post)
                line.add_action(post)
        if not rows:
            section.empty(tr("Всё сделано"))
        return section

    def _opener(self, row: Attention):
        return lambda: self.open_place.emit(row.place)

    def _money(self, rows: list[Money]) -> Section:
        section = Section(tr("Деньги"))
        for m in rows:
            figure = format_minor(m.balance)
            if m.currency_balance is not None:
                figure = f"{m.currency} {format_minor(m.currency_balance)}"
            line = Line(m.name, m.account_code, figure, "negative" if m.balance < 0 else "")
            section.add(line).opens(lambda: self.open_place.emit(("bank",)))
        if not rows:
            section.empty(tr("Нет движения денег"))
        return section

    def _rates(self, shown: list[DayRate]) -> Section:
        section = Section(tr("Курсы"))
        for r in shown:
            section.add(self._rate_line(r))
        if not shown:
            section.empty(tr("Валют нет"))
        return section

    def _backup(self) -> Section:
        """When the company was last copied — so a forgotten copy is seen (D97)."""
        section = Section(tr("Резервная копия"))
        made = self.s.last_backup()
        if made is None:
            line = Line(tr("Копий ещё нет"), tr("копия делается при закрытии компании"))
        else:
            line = Line(tr("Последняя копия"), "", made.strftime("%d.%m.%Y %H:%M"))
        section.add(line).opens(self.open_backups.emit)
        return section

    def _rate_line(self, r: DayRate) -> Line:
        if r.rate is None:
            line = Line(r.code, "", "—")
        else:
            nominal = f"{r.rate.nominal} {r.code}" if r.rate.nominal != 1 else r.code
            note = "" if r.of_the_day else tr("на {date}", date=ru_date(r.rate.rate_date))
            line = Line(nominal, note, format_rate(r.rate.rate, r.rate.nominal))
        line.opens(lambda: self.open_place.emit(("currencies",)))
        if not r.of_the_day:
            load = button(tr("Загрузить"), "flat", tr("Курсы ЦБА на {date}", date=ru_date(r.day)))
            load.clicked.connect(lambda _=False: self.load_rates())
            hide_when_viewing(self.s.read_only, load)
            line.add_action(load)
        return line

    # ---- what the buttons do ---------------------------------------------------------

    def post_drafts(self) -> None:
        """«Провести все»: the journal's drafts up to the working date; «Undo» unposts."""
        led, cid = self.s.ledger, self.s.company_id
        posted, left = led.post_drafts(cid, self.s.working_date)
        message = tr("Проведено документов: {n}", n=len(posted))
        if left:
            number, why = left[0]
            message += "   ·   " + tr("№{n} не проведён: {why}", n=number, why=why)
        self.refresh()
        if posted:
            self.s.notify_undoable(message, lambda: self._unpost(posted))
        else:
            self.s.notify(message)

    def _unpost(self, posted: list[int]) -> None:
        """«Undo» of «Провести все»: the same documents are drafts again."""
        for doc_id in posted:
            self.s.ledger.unpost(self.s.company_id, doc_id)
        self.refresh()

    def load_rates(self) -> None:
        """CBAR rates of the working date (the currencies page loads a period)."""
        day = self.s.working_date
        try:
            self.s.ledger.import_rates(self.s.company_id, day, self.s.fetch_rates(day))
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.catalog.reload()
        self.refresh()
        self.s.notify(tr("Загружены курсы ЦБА за {n} дн.", n=1))
