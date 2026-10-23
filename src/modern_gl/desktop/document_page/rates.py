"""Rates of a currency document: the rate of the date offered, a note when it is not loaded
yet, the Central Bank's rates loaded from here."""

from __future__ import annotations

from modern_gl.application.currencies import rate_on
from modern_gl.desktop.document_page.form import DocumentForm
from modern_gl.desktop.rate_note import load_day_rates
from modern_gl.desktop.widgets import (
    edited_date,
    ru_date,
)
from modern_gl.i18n import tr


class RatesPart(DocumentForm):
    def _stale_rates(self) -> list[tuple[str, str | None]]:
        """Currencies of lines on the offered rate that have no rate set for the document
        date itself: (code, date of the rate used or None)."""
        day = edited_date(self.date)
        found: dict[str, str | None] = {}
        for i, r in enumerate(self.model.rows):
            if r.currency_id is None or not r.rate_auto or not self.model.in_currency(i):
                continue
            rate = rate_on(self.s.conn, self.s.company_id, r.currency_id, day)
            if rate is None or rate.rate_date < day.isoformat():
                code = self.s.catalog.currencies[r.currency_id].code
                found[code] = rate.rate_date if rate else None
        return sorted(found.items())

    def _update_rate_note(self) -> None:
        stale = [] if self.model.read_only else self._stale_rates()
        if not stale:
            self.rate_note.hide()
            return
        day = ru_date(edited_date(self.date).isoformat())
        parts = [
            tr("курс {code} от {old}", code=code, old=ru_date(old))
            if old
            else tr("нет курса {code}", code=code)
            for code, old in stale
        ]
        self.rate_text.setText(
            tr("На {date} курс не загружен: {what}", date=day, what=", ".join(parts))
        )
        self.rate_note.show()

    def load_rates(self) -> None:
        """Official rates of the document date from cbar.az; the lines take them."""
        if not load_day_rates(self.s, edited_date(self.date), self.show_error):
            return
        self.error.hide()
        self.model.refresh_rates()
        self._update_rate_note()

    def _date_changed(self, *_) -> None:
        if not self.model.read_only:
            self.error.hide()
            self.model.refresh_rates()
