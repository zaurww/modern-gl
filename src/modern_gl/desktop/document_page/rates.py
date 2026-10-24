"""Rates of a currency document: the rate of the date offered, a note when it is not loaded
yet, the Central Bank's rates loaded from here."""

from __future__ import annotations

from modern_gl.application.currencies import missing_rates_text
from modern_gl.desktop.document_page.form import DocumentForm
from modern_gl.desktop.rate_note import load_day_rates
from modern_gl.desktop.widgets import (
    edited_date,
)


class RatesPart(DocumentForm):
    def _update_rate_note(self) -> None:
        """Lines on the offered rate whose currency has no rate set for the date itself."""
        offered = [
            r.currency_id
            for i, r in enumerate(self.model.rows)
            if r.currency_id is not None and r.rate_auto and self.model.in_currency(i)
        ]
        text = (
            ""
            if self.model.read_only
            else missing_rates_text(self.s.conn, self.s.company_id, offered, edited_date(self.date))
        )
        self.rate_text.setText(text)
        self.rate_note.setVisible(bool(text))

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
