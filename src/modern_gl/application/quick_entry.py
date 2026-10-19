"""Quick entry: a document typed as one line of text (like plain-text accounting).

    26 аренда / 60 альфа, договор 400 Аренда за март
    05.03 50 / 51 kapital 2000 В кассу
    52 kapital usd / 51 1000 usd Покупка валюты
    #продажа 1180 бета

A line is  [date]  Dt-account [subconto, subconto]  /  Kt-account [subconto…]  amount
[currency]  [memo]. Accounts are codes (or a unique part of a name); subconto are parts
of names, separated by commas, in the order of the account's subconto; "+Name" adds a
new element. The first number after the Kt account is the amount, written without spaces
(1234,50 or 1234.50 — a space separates words); on a currency line it
is in the currency, and manat follow at the rate of the date. Several postings of one
document are separated by ";" or line breaks.

"#template amount [subconto, …]" uses an entry template: S = the amount, and the pieces
after it fill the subconto the template leaves empty (what does not fit is the memo).

Plain Python, no Qt: the UI shows `describe()` while the user types.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.application.queries import TemplateData
from modern_gl.domain import formula
from modern_gl.domain.currency import format_unit_rate, to_base
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import fold, tr

DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?$")
NEW = "+"


@dataclass
class QuickLine:
    debit: int | None = None
    debit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    credit: int | None = None
    credit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    memo: str = ""
    currency_id: int | None = None
    currency_amount: int | None = None
    rate: Fraction | None = None


@dataclass
class NewValue:
    """A "+Name" element to add before posting; `cells` are (line, side, position)."""

    kind_id: int
    name: str
    cells: list[tuple[int, str, int]] = field(default_factory=list)


@dataclass
class QuickEntry:
    doc_date: date | None = None
    memo: str = ""
    lines: list[QuickLine] = field(default_factory=list)
    new_values: list[NewValue] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # subconto left empty, for the preview


def _number(token: str) -> int | None:
    text = token.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace("," if text.index(",") < text.index(".") else ".", "")
    if not re.fullmatch(r"\d+([.,]\d{1,2})?", text):
        return None
    value = to_minor(text.replace(",", "."))
    return value if value > 0 else None


def _date(token: str, today: date) -> date | None:
    m = DATE.match(token)
    if not m:
        return None
    day, month, year = int(m[1]), int(m[2]), m[3]
    y = today.year if year is None else int(year) + (2000 if len(year) == 2 else 0)
    try:
        return date(y, month, day)
    except ValueError:
        return None


class _Parser:
    def __init__(
        self,
        catalog: Catalog,
        templates: Sequence[TemplateData],
        rate_for: Callable[[int, date], Fraction | None],
        today: date,
    ) -> None:
        self.cat = catalog
        self.templates = templates
        self.rate_for = rate_for
        self.today = today
        self.entry = QuickEntry()

    def parse(self, text: str) -> QuickEntry:
        parts = [p.strip() for p in re.split(r"[;\n]", text) if p.strip()]
        if not parts:
            raise ValidationError(tr("пустая строка"))
        first = parts[0].split()
        if (day := _date(first[0], self.today)) is not None:
            self.entry.doc_date = day
            parts[0] = " ".join(first[1:])
            if not parts[0]:
                parts.pop(0)
        if not parts:
            raise ValidationError(tr("после даты нет проводки"))
        for n, part in enumerate(parts, start=1):
            if part.startswith("#"):
                self._template(n, part[1:])
            else:
                self._posting(n, part)
        if not self.entry.memo:
            self.entry.memo = next((ln.memo for ln in self.entry.lines if ln.memo), "")
        return self.entry

    # ---- a posting line ----------------------------------------------------------

    def _posting(self, n: int, text: str) -> None:
        if "/" not in text:
            raise ValidationError(
                tr("строка {n}: дебет и кредит разделяются «/»: 26 / 60 400", n=n)
            )
        left, right = text.split("/", 1)
        dt_words, ct_words = left.split(), right.split()
        if not dt_words:
            raise ValidationError(tr("строка {n}: не указан счёт дебета", n=n))
        if not ct_words:
            raise ValidationError(tr("строка {n}: не указан счёт кредита", n=n))
        line = QuickLine()
        index = len(self.entry.lines)
        debit = self._account(n, dt_words[0])
        credit = self._account(n, ct_words[0])
        line.debit, line.credit = debit.id, credit.id
        at = next((i for i, w in enumerate(ct_words[1:], start=1) if _number(w)), None)
        if at is None:
            raise ValidationError(tr("строка {n}: не указана сумма", n=n))
        self._subconto(n, index, line, "debit", debit, " ".join(dt_words[1:]))
        self._subconto(n, index, line, "credit", credit, " ".join(ct_words[1:at]))
        amount = _number(ct_words[at])
        rest = ct_words[at + 1 :]
        currency = None
        if rest and (found := self._currency_code(rest[0])) is not None:
            currency, rest = found, rest[1:]
        line.memo = " ".join(rest)
        self._amount(n, line, amount, currency, (debit, credit))
        self.entry.lines.append(line)

    def _account(self, n: int, text: str) -> AccountInfo:
        try:
            return self.cat.resolve_account(text)
        except LookupError as e:
            raise ValidationError(tr("строка {n}: {error}", n=n, error=str(e).strip("'\""))) from e

    def _subconto(
        self, n: int, index: int, line: QuickLine, side: str, acc: AccountInfo, text: str
    ) -> None:
        pieces = [p.strip() for p in text.split(",") if p.strip()]
        positions = [i for i, kind in enumerate(acc.sc_kinds) if kind is not None]
        if len(pieces) > len(positions):
            raise ValidationError(
                tr(
                    "строка {n}: у счёта {code} субконто {k}, а указано {m}: {text}",
                    n=n,
                    code=acc.short,
                    k=len(positions),
                    m=len(pieces),
                    text=text,
                )
            )
        values = getattr(line, f"{side}_sc")
        for pos, piece in zip(positions, pieces, strict=False):
            values[pos] = self._value(n, index, side, pos, acc.sc_kinds[pos], piece)
        for pos in positions[len(pieces) :]:
            self.entry.missing.append(
                f"{tr('Дт' if side == 'debit' else 'Кт')} {acc.short}: "
                f"{self.cat.kinds[acc.sc_kinds[pos]]}"
            )

    def _value(self, n: int, index: int, side: str, pos: int, kind: int, piece: str):
        if piece.startswith(NEW):
            name = piece[len(NEW) :].strip()
            if not name:
                raise ValidationError(tr("строка {n}: после «+» нет названия", n=n))
            new = next(
                (v for v in self.entry.new_values if v.kind_id == kind and v.name == name), None
            )
            if new is None:
                new = NewValue(kind, name)
                self.entry.new_values.append(new)
            new.cells.append((index, side, pos))
            return None
        try:
            value = self.cat.resolve_value(kind, piece)
        except LookupError as e:
            raise ValidationError(tr("строка {n}: {error}", n=n, error=str(e).strip("'\""))) from e
        if value is None:
            raise ValidationError(
                tr(
                    "строка {n}: «{text}» нет в справочнике «{kind}» "
                    "(чтобы добавить, напишите +{text})",
                    n=n,
                    text=piece,
                    kind=self.cat.kinds[kind],
                )
            )
        return value

    def _currency_code(self, word: str) -> int | None:
        code = word.upper()
        return next((c.id for c in self.cat.active_currencies if c.code == code), None)

    def _amount(self, n, line: QuickLine, amount, currency, accounts) -> None:
        if not any(a.currency for a in accounts):
            if currency is not None:
                raise ValidationError(
                    tr("строка {line}: валюта указана, но счета без валютного учёта", line=n)
                )
            line.amount = amount
            return
        if currency is None:  # the currency of a chosen element (a USD bank account)
            currency = next(
                (
                    self.cat.value(v).currency_id
                    for v in (*line.debit_sc, *line.credit_sc)
                    if v is not None and self.cat.value(v).currency_id is not None
                ),
                None,
            )
        if currency is None:
            raise ValidationError(
                tr("строка {n}: счёт в валюте — укажите валюту после суммы: 1000 USD", n=n)
            )
        day = self.entry.doc_date or self.today
        rate = self.rate_for(currency, day)
        if rate is None:
            code = self.cat.currencies[currency].code
            raise ValidationError(
                tr("нет курса {code} на {date}", code=code, date=f"{day:%d.%m.%Y}")
            )
        line.currency_id, line.currency_amount, line.rate = currency, amount, rate
        line.amount = to_base(amount, rate)

    # ---- a template line ---------------------------------------------------------

    def _template(self, n: int, text: str) -> None:
        words = text.split()
        at = next((i for i, w in enumerate(words) if _number(w)), len(words))
        name = " ".join(words[:at])
        template = self._find_template(n, name)
        amount = _number(words[at]) if at < len(words) else None
        try:
            amounts = formula.compute([ln.formula for ln in template.lines], amount)
        except ValidationError as e:
            raise ValidationError(tr("строка {n}: {error}", n=n, error=e)) from e
        first = len(self.entry.lines)
        for ln, value in zip(template.lines, amounts, strict=True):
            self.entry.lines.append(
                QuickLine(
                    ln.debit_account_id,
                    list(ln.debit_subconto),
                    ln.credit_account_id,
                    list(ln.credit_subconto),
                    value if value and value > 0 else None,
                    ln.memo,
                )
            )
        memo = self._fill_template(n, first, " ".join(words[at + 1 :]))
        self.entry.memo = memo or template.memo or template.name

    def _find_template(self, n: int, name: str) -> TemplateData:
        needle = fold(name)
        if not needle:
            raise ValidationError(tr("строка {n}: после «#» укажите шаблон", n=n))
        found = [t for t in self.templates if fold(t.name).startswith(needle)] or [
            t for t in self.templates if needle in fold(t.name)
        ]
        exact = [t for t in found if fold(t.name) == needle]
        found = exact or found
        if len(found) != 1:
            if not found:
                raise ValidationError(tr("строка {n}: шаблон «{name}» не найден", n=n, name=name))
            names = ", ".join(t.name for t in found[:5])
            raise ValidationError(
                tr(
                    "строка {n}: «{name}» подходит к нескольким шаблонам: {names}",
                    n=n,
                    name=name,
                    names=names,
                )
            )
        return found[0]

    def _fill_template(self, n: int, first: int, text: str) -> str:
        """Pieces after the amount fill empty subconto of the template's lines (the same
        directory everywhere it is empty); the first piece that fits nowhere starts the memo."""
        pieces = [p.strip() for p in text.split(",") if p.strip()]
        lines = self.entry.lines[first:]
        slots: dict[int, list[tuple[QuickLine, str, int]]] = {}
        for ln in lines:
            for side in ("debit", "credit"):
                account = getattr(ln, side)
                if account is None:
                    continue
                values = getattr(ln, f"{side}_sc")
                for pos, kind in enumerate(self.cat.accounts[account].sc_kinds):
                    if kind is not None and values[pos] is None:
                        slots.setdefault(kind, []).append((ln, side, pos))
        for i, piece in enumerate(pieces):
            kind = next(
                (k for k in slots if piece.startswith(NEW) or self._resolves(k, piece)),
                None,
            )
            if kind is None:
                return ", ".join(pieces[i:])
            for ln, side, pos in slots.pop(kind):
                index = self.entry.lines.index(ln)
                getattr(ln, f"{side}_sc")[pos] = self._value(n, index, side, pos, kind, piece)
        for kind, cells in slots.items():
            for ln, side, _pos in cells:
                acc = self.cat.accounts[getattr(ln, side)]
                self.entry.missing.append(
                    f"{tr('Дт' if side == 'debit' else 'Кт')} {acc.short}: {self.cat.kinds[kind]}"
                )
        return ""

    def _resolves(self, kind: int, piece: str) -> bool:
        try:
            return self.cat.resolve_value(kind, piece) is not None
        except LookupError:
            return False


def parse(
    text: str,
    catalog: Catalog,
    templates: Sequence[TemplateData] = (),
    rate_for: Callable[[int, date], Fraction | None] = lambda _c, _d: None,
    today: date | None = None,
) -> QuickEntry:
    """Raises ValidationError with a message for the user."""
    return _Parser(catalog, templates, rate_for, today or date.today()).parse(text)


def describe(entry: QuickEntry, catalog: Catalog) -> str:
    """How the line was understood, one posting per line, for the preview."""

    def side(account: int | None, values: list[int | None], new: list[str]) -> str:
        if account is None:
            return "?"
        names = [catalog.value(v).name for v in values if v is not None] + new
        acc = catalog.accounts[account].short
        return f"{acc} · {', '.join(names)}" if names else acc

    result = []
    for i, ln in enumerate(entry.lines):
        new = {
            s: [f"+{v.name}" for v in entry.new_values if any(c[:2] == (i, s) for c in v.cells)]
            for s in ("debit", "credit")
        }
        amount = format_minor(ln.amount) if ln.amount else "?"
        if ln.currency_id is not None and ln.currency_amount is not None:
            code = catalog.currencies[ln.currency_id].code
            rate = format_unit_rate(ln.rate) if ln.rate is not None else "?"
            amount = f"{format_minor(ln.currency_amount)} {code} × {rate} = {amount}"
        text = (
            f"{tr('Дт')} {side(ln.debit, ln.debit_sc, new['debit'])}   →   "
            f"{tr('Кт')} {side(ln.credit, ln.credit_sc, new['credit'])}      {amount}"
        )
        if ln.memo:
            text += f"      «{ln.memo}»"
        result.append(text)
    return "\n".join(result)
