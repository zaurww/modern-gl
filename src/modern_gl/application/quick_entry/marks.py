"""What each part of the quick entry line was understood as, with its place in the text:
the line colours the parts while the user types (like Todoist's Quick Add)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.application.queries import TemplateData
from modern_gl.application.quick_entry.parser import NEW, amount_index, token_date, token_number
from modern_gl.domain.invoice import MARK as INVOICE_MARK
from modern_gl.i18n import fold

# kinds of parts: the date, an account, an element of a directory, a new one ("+Name"),
# the amount, its currency, an e-qaimə number, a template; "unknown" names nothing
KINDS = ("date", "account", "value", "new", "amount", "currency", "invoice", "template", "unknown")


@dataclass(frozen=True)
class Mark:
    start: int
    end: int
    kind: str


def marks(
    text: str, catalog: Catalog, templates: Sequence[TemplateData] = (), today: date | None = None
) -> list[Mark]:
    """The understood parts of the line, in order; the memo is left unmarked."""
    return _Marker(catalog, templates, today or date.today()).line(text)


class _Marker:
    def __init__(self, catalog: Catalog, templates: Sequence[TemplateData], today: date) -> None:
        self.cat = catalog
        self.templates = templates
        self.today = today
        self.found: list[Mark] = []

    def line(self, text: str) -> list[Mark]:
        first = True
        for seg in re.finditer(r"[^;\n]+", text):
            words = _words(seg.group(), seg.start())
            if not words:
                continue
            start = seg.start()
            if first and token_date(words[0][2], self.today) is not None:
                self._mark(words[0][0], words[0][1], "date")
                start = words[0][1]
            first = False
            body = text[start : seg.end()]
            if body.strip().startswith("#"):
                self._template(_words(body, start))
            else:
                self._posting(body, start)
        return self.found

    def _mark(self, start: int, end: int, kind: str) -> None:
        self.found.append(Mark(start, end, kind))

    # ---- a posting ---------------------------------------------------------------

    def _posting(self, body: str, offset: int) -> None:
        slash = body.find("/")
        left = body if slash < 0 else body[:slash]
        self._side(left, offset, credit=False)
        if slash >= 0:
            self._side(body[slash + 1 :], offset + slash + 1, credit=True)

    def _side(self, text: str, offset: int, credit: bool) -> None:
        words = _words(text, offset)
        if not words:
            return
        start, end, code = words[0]
        try:
            account = self.cat.resolve_account(code)
        except LookupError:
            self._mark(start, end, "unknown")
            return
        self._mark(start, end, "account")
        at = len(words)
        if credit:
            found = amount_index(self.cat, account, [w for _, _, w in words])
            at = len(words) if found is None else found
        if at > 1:
            self._subconto(account, text[end - offset : words[at - 1][1] - offset], end)
        if at < len(words):
            self._after_amount(words[at:])

    def _subconto(self, account: AccountInfo, text: str, offset: int) -> None:
        slots = [(i, k) for i, k in enumerate(account.sc_kinds) if k is not None]
        values: list[int | None] = [None, None, None]
        for n, piece in enumerate(re.finditer(r"[^,]+", text)):
            name = piece.group().strip()
            if not name:
                continue
            start = offset + piece.start() + piece.group().index(name)
            end = start + len(name)
            if n >= len(slots):
                self._mark(start, end, "unknown")
                continue
            pos, kind = slots[n]
            if name.startswith(NEW):
                self._mark(start, end, "new" if name[len(NEW) :].strip() else "unknown")
                continue
            try:
                found = self.cat.resolve_value(kind, name, self.cat.owner_in(account, values, pos))
            except LookupError:
                found = None
            values[pos] = found
            self._mark(start, end, "unknown" if found is None else "value")

    def _after_amount(self, words: list[tuple[int, int, str]]) -> None:
        start, end, _ = words[0]
        self._mark(start, end, "amount")
        rest = words[1:]
        if rest and any(c.code == rest[0][2].upper() for c in self.cat.active_currencies):
            self._mark(rest[0][0], rest[0][1], "currency")
            rest = rest[1:]
        if rest and rest[0][2].startswith(INVOICE_MARK):
            self._mark(rest[0][0], rest[0][1], "invoice")

    # ---- a template --------------------------------------------------------------

    def _template(self, words: list[tuple[int, int, str]]) -> None:
        at = next((i for i, w in enumerate(words) if token_number(w[2])), len(words))
        if at == 0:
            return
        name = fold(" ".join(w for _, _, w in words[:at])[1:])
        known = bool(name) and any(name in fold(t.name) for t in self.templates)  # as parse
        self._mark(words[0][0], words[at - 1][1], "template" if known else "unknown")
        if at < len(words):
            self._mark(words[at][0], words[at][1], "amount")


def _words(text: str, offset: int) -> list[tuple[int, int, str]]:
    return [(offset + m.start(), offset + m.end(), m.group()) for m in re.finditer(r"\S+", text)]
