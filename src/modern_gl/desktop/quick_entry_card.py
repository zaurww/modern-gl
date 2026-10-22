"""The quick entry line as a card under it (like Fantastical's preview): the date and
memo, then each posting — Dt → Kt with their elements, the amount on the right. What is
still empty stands grey in its place (a click finishes it in the form); a new element
is amber."""

from __future__ import annotations

from datetime import date
from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from modern_gl.application.catalog import Catalog
from modern_gl.application.quick_entry import QuickEntry
from modern_gl.application.quick_entry.card import CardLine, Part, card
from modern_gl.desktop.theme import P, fonts
from modern_gl.i18n import tr


class EntryCard(QFrame):
    finish = Signal()  # a grey place clicked: finish the document in the form

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("summary")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.text = QLabel()
        self.text.setFont(fonts().body)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.text.linkActivated.connect(lambda _link: self.finish.emit())
        lay.addWidget(self.text)

    def show_entry(self, entry: QuickEntry, catalog: Catalog, day: date) -> None:
        head = _span(f"{day:%d.%m.%Y}", P.secondary)
        if entry.memo:
            head += "&nbsp;&nbsp;·&nbsp;&nbsp;" + _span(entry.memo, P.text)
        rows = [f'<tr><td colspan="4" style="padding-bottom: 6px">{head}</td></tr>']
        rows += [_row(line) for line in card(entry, catalog)]
        self.text.setText(
            f'<table width="100%" cellspacing="0" cellpadding="2">{"".join(rows)}</table>'
        )
        self.show()


def _row(line: CardLine) -> str:
    amount = _part(line.amount)
    if line.in_manat:
        amount += "&nbsp;" + _span(line.in_manat, P.secondary)
    notes = [n for n in (line.memo, f"e-qaimə {line.invoice}" if line.invoice else "") if n]
    note = f"<br>{_span('   ·   '.join(notes), P.secondary)}" if notes else ""
    debit = f"{_span(tr('Дт'), P.tertiary)}&nbsp;&nbsp;{_side(line.debit)}{note}"
    return (
        f'<tr><td width="45%">{debit}</td>'
        f'<td width="4%">{_span("→", P.tertiary)}</td>'
        f'<td width="36%">{_span(tr("Кт"), P.tertiary)}&nbsp;&nbsp;{_side(line.credit)}</td>'
        f'<td align="right">&nbsp;&nbsp;&nbsp;{amount}</td></tr>'
    )


def _side(parts: list[Part]) -> str:
    return _span("&nbsp;·&nbsp;", P.tertiary, raw=True).join(_part(p) for p in parts)


def _part(part: Part) -> str:
    if part.kind == "account":
        return f'<span style="color: {P.text}; font-weight: 600">{escape(part.text)}</span>'
    if part.kind == "amount":
        return f'<span style="color: {P.text}; font-weight: 600">{escape(part.text)}</span>'
    if part.kind == "new":
        return _span(part.text, P.amber)
    if part.kind == "missing":  # a click opens the form to fill it in
        style = f"color: {P.tertiary}; text-decoration: none"
        return f'<a href="form" style="{style}">{escape(part.text)}?</a>'
    return _span(part.text, P.text)


def _span(text: str, color: str, raw: bool = False) -> str:
    return f'<span style="color: {color}">{text if raw else escape(text)}</span>'
