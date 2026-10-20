"""Quick entry: a document typed as one line of text (like plain-text accounting).

    26 аренда / 60 альфа, договор 400 Аренда за март
    05.03 50 / 51 kapital 2000 В кассу
    52 kapital usd / 51 1000 usd Покупка валюты
    #продажа 1180 бета

A line is  [date]  Dt-account [subconto, subconto]  /  Kt-account [subconto…]  amount
[currency]  [№e-qaimə]  [memo]. Accounts are codes (or a unique part of a name); subconto are parts
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
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction

from modern_gl.application.catalog import AccountInfo, Catalog, search
from modern_gl.application.queries import TemplateData
from modern_gl.domain import formula
from modern_gl.domain.currency import format_unit_rate, to_base
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import MARK as INVOICE_MARK
from modern_gl.domain.invoice import normalize_invoice
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
    invoice: str = ""  # «№MT2410123456» after the amount


@dataclass
class NewValue:
    """A "+Name" element to add before posting; `cells` are (line, side, position)."""

    kind_id: int
    name: str
    cells: list[tuple[int, str, int]] = field(default_factory=list)
    owner: int | NewValue | None = None  # "+Договор" next to a counterparty (maybe new too)
    id: int | None = None  # set once it is added


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
        at = self._amount_at(credit, ct_words)
        if at is None:
            raise ValidationError(tr("строка {n}: не указана сумма", n=n))
        self._subconto(n, index, line, "debit", debit, " ".join(dt_words[1:]))
        self._subconto(n, index, line, "credit", credit, " ".join(ct_words[1:at]))
        amount = _number(ct_words[at])
        rest = ct_words[at + 1 :]
        currency = None
        if rest and (found := self._currency_code(rest[0])) is not None:
            currency, rest = found, rest[1:]
        if rest and rest[0].startswith(INVOICE_MARK):
            line.invoice = normalize_invoice(rest[0]) or ""
            if not line.invoice:
                raise ValidationError(tr("строка {n}: после «№» нет номера e-qaimə", n=n))
            rest = rest[1:]
        line.memo = " ".join(rest)
        self._amount(n, line, amount, currency, (debit, credit))
        self.entry.lines.append(line)

    def _amount_at(self, credit: AccountInfo, words: list[str]) -> int | None:
        """Index of the amount among the Kt words. Names may hold numbers ("Фактура 15"):
        the first number after which the subconto text names elements exactly wins,
        else the first number."""
        numbers = [i for i, w in enumerate(words[1:], start=1) if _number(w)]
        for at in numbers:
            if self._names_exactly(credit, " ".join(words[1:at])):
                return at
        return numbers[0] if numbers else None

    def _names_exactly(self, acc: AccountInfo, text: str) -> bool:
        pieces = [p.strip() for p in text.split(",") if p.strip()]
        slots = [(i, k) for i, k in enumerate(acc.sc_kinds) if k is not None]
        if not pieces or len(pieces) > len(slots):
            return not pieces
        last = pieces[-1]
        if last.startswith(NEW):
            return True
        kind = slots[len(pieces) - 1][1]
        return any(fold(v.name) == fold(last) for v in self.cat.values(kind))

    def _account(self, n: int, text: str) -> AccountInfo:
        try:
            return self.cat.resolve_account(text)
        except LookupError as e:
            raise ValidationError(tr("строка {n}: {error}", n=n, error=str(e).strip("'\""))) from e

    def _subconto(
        self, n: int, index: int, line: QuickLine, side: str, acc: AccountInfo, text: str
    ) -> None:
        pieces = [p.strip() for p in text.split(",") if p.strip()]
        slots = [(i, kind) for i, kind in enumerate(acc.sc_kinds) if kind is not None]
        if len(pieces) > len(slots):
            raise ValidationError(
                tr(
                    "строка {n}: у счёта {code} субконто {k}, а указано {m}: {text}",
                    n=n,
                    code=acc.short,
                    k=len(slots),
                    m=len(pieces),
                    text=text,
                )
            )
        values = getattr(line, f"{side}_sc")
        for (pos, kind), piece in zip(slots, pieces, strict=False):
            owner = self._owner(index, side, acc, values, pos)
            values[pos] = self._value(n, index, side, pos, kind, piece, owner)
        for _, kind in slots[len(pieces) :]:
            self.entry.missing.append(
                f"{tr('Дт' if side == 'debit' else 'Кт')} {acc.short}: {self.cat.kinds[kind]}"
            )

    def _owner(
        self, index: int, side: str, acc: AccountInfo, values: list[int | None], pos: int
    ) -> int | NewValue | None:
        """The counterparty of a contract at `pos`: chosen on the same side, or new."""
        slot = self.cat.owner_slot(acc, pos)
        if slot is None:
            return None
        if values[slot] is not None:
            return values[slot]
        return next((v for v in self.entry.new_values if (index, side, slot) in v.cells), None)

    def _value(
        self,
        n: int,
        index: int,
        side: str,
        pos: int,
        kind: int,
        piece: str,
        owner: int | NewValue | None = None,
    ):
        if piece.startswith(NEW):
            name = piece[len(NEW) :].strip()
            if not name:
                raise ValidationError(tr("строка {n}: после «+» нет названия", n=n))
            new = next(
                (
                    v
                    for v in self.entry.new_values
                    if v.kind_id == kind and v.name == name and v.owner == owner
                ),
                None,
            )
            if new is None:
                new = NewValue(kind, name, owner=owner)
                self.entry.new_values.append(new)
            new.cells.append((index, side, pos))
            return None
        try:  # next to a new counterparty only the common contracts are there
            value = self.cat.resolve_value(
                kind, piece, -1 if isinstance(owner, NewValue) else owner
            )
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
        currency_accounts = [a for a in accounts if a.currency]
        if not currency_accounts:
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
            if all(a.currency_optional for a in currency_accounts):
                line.amount = amount  # 60 / 62 with a local partner: manat
                return
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
                values = getattr(ln, f"{side}_sc")
                owner = self._owner(index, side, self.cat.accounts[getattr(ln, side)], values, pos)
                values[pos] = self._value(n, index, side, pos, kind, piece, owner)
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
        if ln.invoice:
            text += f"      e-qaimə {ln.invoice}"
        if ln.memo:
            text += f"      «{ln.memo}»"
        result.append(text)
    return "\n".join(result)


# ---- suggestions while typing ---------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    label: str  # shown in the list
    insert: str  # replaces the word being typed


@dataclass
class Suggestions:
    start: int  # where the word being typed starts; it is replaced up to the cursor
    items: list[Suggestion] = field(default_factory=list)
    typed: bool = False  # something is typed: the best match may be taken with Enter


def suggest(
    text: str,
    cursor: int,
    catalog: Catalog,
    templates: Sequence[TemplateData] = (),
    recent: Callable[[int, int], list[int]] = lambda _account, _position: [],
) -> Suggestions:
    """What fits where the cursor is: accounts, then the elements of their subconto in
    order (recently used on the account first; the contracts of the counterparty
    chosen), a currency after the amount, templates after "#". Choosing an element adds
    what comes next: ", " for the next subconto, " / " after the Dt side."""
    before = text[:cursor]
    seg_start = max(before.rfind(";"), before.rfind("\n")) + 1
    segment = before[seg_start:]
    lead = len(segment) - len(segment.lstrip())
    words = segment.split()
    date_done = len(words) > 1 or segment.rstrip() != segment  # "05.03 " — the date is typed
    if words and date_done and _date(words[0], date.today()) is not None:
        lead = segment.index(words[0]) + len(words[0])
        lead += len(segment[lead:]) - len(segment[lead:].lstrip())
    body = segment[lead:]
    offset = seg_start + lead
    if body.startswith("#"):
        return _suggest_template(body, offset, templates)
    if "/" in body:
        slash = body.index("/")
        side_text, side_start, credit = body[slash + 1 :], offset + slash + 1, True
    else:
        side_text, side_start, credit = body, offset, False
    stripped = side_text.lstrip()
    side_start += len(side_text) - len(stripped)
    if not stripped or " " not in stripped:  # the account is being typed
        if not stripped and not credit:
            return Suggestions(side_start)
        items = [Suggestion(a.label, f"{a.short} ") for a in catalog.leaf_accounts]
        return _filter(items, stripped, side_start)
    word = stripped.split()[0]
    try:
        account = catalog.resolve_account(word)
    except LookupError:
        return Suggestions(cursor)
    rest_start = side_start + len(word)
    rest = before[rest_start:cursor]
    found = _suggest_subconto(catalog, account, rest, rest_start, credit, recent)
    if found.items or not credit:
        return found
    return _suggest_currency(catalog, account, rest, rest_start)


def _filter(items: list[Suggestion], typed: str, start: int) -> Suggestions:
    labels = search([i.label for i in items], typed)
    by_label = {i.label: i for i in items}
    return Suggestions(start, [by_label[label] for label in labels], bool(typed.strip()))


def _suggest_subconto(
    catalog: Catalog,
    account: AccountInfo,
    rest: str,
    rest_start: int,
    credit: bool,
    recent: Callable[[int, int], list[int]],
) -> Suggestions:
    slots = [(i, k) for i, k in enumerate(account.sc_kinds) if k is not None]
    pieces = rest.split(",")
    n = len(pieces) - 1  # the piece being typed
    if n >= len(slots) or (not rest.startswith(" ") and n == 0):
        return Suggestions(rest_start + len(rest))
    typed = pieces[-1].lstrip()
    start = rest_start + len(rest) - len(typed)
    values: list[int | None] = [None, None, None]
    for (pos, kind), piece in zip(slots, pieces[:-1], strict=False):
        with suppress(LookupError):  # a piece that names nothing yet: no owner from it
            values[pos] = catalog.resolve_value(kind, piece, catalog.owner_in(account, values, pos))
    pos, kind = slots[n]
    owner = catalog.owner_in(account, values, pos)
    last = n == len(slots) - 1
    tail = " " if credit and last else (" / " if last else ", ")
    offered = catalog.values(kind, owner)
    name = typed.strip()
    # on the Kt side the amount and the memo may follow any subconto: "Бета 400 Услуги"
    amount_typed = credit and any(_number(w) for w in name.split()[1:])
    if typed.startswith(NEW):  # "+Name": only the new element, once the name is typed
        if not name[1:].strip() or amount_typed:
            return Suggestions(start)
        return Suggestions(start, _new_value(catalog.kinds[kind], name[1:], tail), True)
    first = [v for v in recent(account.id, pos + 1) if v in {o.id for o in offered}]
    ordered = [catalog.value(v) for v in first] + [v for v in offered if v.id not in first]
    items = [Suggestion(v.label, v.name + tail) for v in ordered]  # found by VÖEN too
    found = _filter(items, typed, start)
    known = any(fold(v.name) == fold(name) for v in offered)
    if (name or not offered) and not known and not amount_typed:
        found.items += _new_value(catalog.kinds[kind], name, tail)
    return found


def _new_value(kind: str, name: str, tail: str) -> list[Suggestion]:
    """Add an element right from the line: it is created when the document is posted."""
    name = name.strip()
    if not name:
        return [Suggestion(tr("+ Новый элемент «{kind}» — напишите название", kind=kind), NEW)]
    return [
        Suggestion(tr("+ Добавить «{name}» в «{kind}»", name=name, kind=kind), NEW + name + tail)
    ]


def _suggest_currency(
    catalog: Catalog, account: AccountInfo, rest: str, rest_start: int
) -> Suggestions:
    """After the amount on a currency account: "400 us" -> USD."""
    words = rest.split()
    if not account.currency or len(words) < 2 or not _number(words[-2]) or rest.endswith(" "):
        return Suggestions(rest_start + len(rest))
    typed = words[-1]
    if len(typed) < 2 or not typed.isalpha():
        return Suggestions(rest_start + len(rest))
    start = rest_start + len(rest) - len(typed)
    items = [
        Suggestion(c.label, f"{c.code} ")
        for c in catalog.active_currencies
        if c.code.startswith(typed.upper())
    ]
    return Suggestions(start, items, True)


def _suggest_template(body: str, offset: int, templates: Sequence[TemplateData]) -> Suggestions:
    typed = body[1:]
    if any(_number(w) for w in typed.split()):
        return Suggestions(offset + len(body))
    items = [Suggestion(f"#{t.name}", f"#{t.name} ") for t in templates]
    return _filter(items, body, offset)
