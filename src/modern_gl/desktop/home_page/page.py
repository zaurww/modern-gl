"""«Bu gün» (D86): one narrow column, three lists over thin lines — «Требует внимания»,
«Деньги», «Курсы». Quiet: no cards, no colored icons; color only for a negative sum."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from modern_gl.desktop.home_page.rows import Line, Section
from modern_gl.desktop.main_window.sidebar import shown_places
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import PageHeader, button, hide_when_viewing, money, ru_date
from modern_gl.domain.currency import format_rate
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.reporting.overview import POST_DRAFTS, Attention, DayRate, attention, rates
from modern_gl.reporting.overview import money as money_rows

COLUMN = 640  # one narrow column: read top to bottom, not across a wide screen


class HomePage(QWidget):
    open_place = Signal(object)  # a sidebar place: («journal»,), («bank»,)…

    def __init__(self, session: Session) -> None:
        super().__init__()
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
        self.body = QVBoxLayout()
        self.body.setSpacing(0)
        self.column.addLayout(self.body)
        self.column.addStretch(1)
        self.sections: list[Section] = []
        self.refresh()

    def title(self) -> str:
        return tr("Сегодня")

    def refresh(self) -> None:
        for section in self.sections:  # hidden at once: deleteLater waits for the loop
            self.body.removeWidget(section)
            section.hide()
            section.deleteLater()
        day = iso_date(self.s.working_date)
        self.header.subtitle.setText(f"{ru_date(day)}   ·   {self.s.company_name}")
        self.sections = [self._attention(day)]
        if not self.s.stock_only:  # no books: no cash or bank accounts to show (D90)
            self.sections.append(self._money(day))
        self.sections.append(self._rates(day))
        for section in self.sections:
            self.body.addWidget(section)

    # ---- the three lists -------------------------------------------------------------

    def _attention(self, day: str) -> Section:
        section = Section(tr("Требует внимания"))
        places = shown_places(self.s.stock_only)
        rows = [r for r in attention(self.s.conn, self.s.company_id, day) if r.place in places]
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

    def _money(self, day: str) -> Section:
        section = Section(tr("Деньги"))
        rows = money_rows(self.s.conn, self.s.company_id, day)
        for m in rows:
            figure = format_minor(m.balance)
            if m.currency_balance is not None:
                figure = f"{m.currency} {format_minor(m.currency_balance)}"
            line = Line(m.name, m.account_code, figure, "negative" if m.balance < 0 else "")
            section.add(line).opens(lambda: self.open_place.emit(("bank",)))
        if not rows:
            section.empty(tr("Нет движения денег"))
        return section

    def _rates(self, day: str) -> Section:
        section = Section(tr("Курсы"))
        shown = rates(self.s.conn, self.s.company_id, day)
        for r in shown:
            section.add(self._rate_line(r))
        if not shown:
            section.empty(tr("Валют нет"))
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
