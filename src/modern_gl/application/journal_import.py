"""Import of many documents from a table (Excel, CSV): one posting per row.

The first row names the columns, in any order, in Russian or Azerbaijani:

    Дата | Документ | Дебет | Субконто | Кредит | Субконто | Сумма | Содержание

Required: Дата, Дебет, Кредит, Сумма. "Субконто" belongs to the account column before
it (1st, 2nd, 3rd); "Субконто Дт 2" says it explicitly. Optional: Документ (rows with
the same value make one document; without it every row is a document), Книга,
Валюта, В валюте, Курс, Содержание.

Names of accounts and elements are matched like in entry (a part of a name is enough).
Elements that are not in a directory become errors, or — when allowed — new elements.
Nothing is written here: `ImportPlan.documents` go to Ledger.import_documents.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.application.currencies import no_rate_text
from modern_gl.application.ledger import ImportedDocument, Ledger, PostingInput
from modern_gl.domain.currency import parse_rate, to_base, unit_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import from_minor, to_minor
from modern_gl.i18n import fold, tr
from modern_gl.i18n_az import AZ

DT, CT = "debit", "credit"


def _names(*sources: str) -> set[str]:
    return {fold(name) for src in sources for name in (src, AZ.get(src, src))}


FIELDS = {
    "date": _names("Дата"),
    "document": _names("Документ", "№", "Номер", "Номер документа", "Sənəd", "Nömrə"),
    "layer": _names("Книга"),
    DT: _names("Дебет", "Дт", "Счёт Дт"),
    CT: _names("Кредит", "Кт", "Счёт Кт"),
    "amount": _names("Сумма", "Сумма AZN"),
    "currency": _names("Валюта"),
    "currency_amount": _names("В валюте", "Сумма в валюте"),
    "rate": _names("Курс"),
    "memo": _names("Содержание", "Комментарий"),
    "invoice": _names("E-qaimə", "E-qaime", "Qaimə", "Номер e-qaimə", "Счёт-фактура"),
}
SUBCONTO = _names("Субконто")
REQUIRED = ("date", DT, CT, "amount")
REQUIRED_NAMES = {"date": "Дата", DT: "Дебет", CT: "Кредит", "amount": "Сумма"}
EXCEL_EPOCH = date(1899, 12, 30)


@dataclass
class Row:
    """One table row as understood, for the preview."""

    row_no: int  # as in the sheet: the header is row 1
    document: int  # index in ImportPlan.documents
    doc_date: date | None = None
    debit: AccountInfo | None = None
    credit: AccountInfo | None = None
    debit_names: list[str] = field(default_factory=list)
    credit_names: list[str] = field(default_factory=list)
    amount: int | None = None
    currency: str = ""
    currency_amount: int | None = None
    memo: str = ""
    invoice: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    rows: list[Row] = field(default_factory=list)
    documents: list[ImportedDocument] = field(default_factory=list)
    # (kind id, name, owner): owner is an id, or -(i + 1) for the i-th new value, or None
    new_values: list[tuple[int, str, int | None]] = field(default_factory=list)
    problem: str = ""  # the table as a whole cannot be read (no header…)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.rows if r.errors) + bool(self.problem)

    def rows_of(self, document: int) -> list[Row]:
        return [r for r in self.rows if r.document == document]


def header(cells: Sequence[str]) -> dict[int, tuple[str, int]]:
    """Column index -> (field, subconto position or 0)."""
    result: dict[int, tuple[str, int]] = {}
    side, pos = None, 0
    for i, cell in enumerate(cells):
        name = fold(cell.strip())
        words = name.split()
        found = next((f for f, names in FIELDS.items() if name in names), None)
        if found is not None:
            result[i] = (found, 0)
            if found in (DT, CT):
                side, pos = found, 0
        elif words and words[0] in SUBCONTO:
            explicit = next((w for w in words[1:] if w in ("дт", "dt", "кт", "kt")), None)
            digits = [int(w) for w in words if w.isdigit()]
            if explicit is not None:
                side, pos = (DT if explicit in ("дт", "dt") else CT), 0
            pos = digits[0] if digits else pos + 1
            if side is not None and 1 <= pos <= 3:
                result[i] = (side, pos)
    return result


def plain_number(text: str) -> str:
    text = text.strip().replace(" ", "").replace(" ", "").replace("'", "")
    if "," in text and "." in text:
        text = text.replace("," if text.index(",") < text.index(".") else ".", "")
    return text.replace(",", ".")


def parse_date(text: str) -> date | None:
    text = text.strip()
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})", text)
    try:
        if m:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return date(year, int(m[2]), int(m[1]))
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        if re.fullmatch(r"\d{5}(\.0+)?", text):  # an Excel date serial number
            return EXCEL_EPOCH + timedelta(days=int(float(text)))
    except ValueError:
        return None
    return None


class _Reader:
    def __init__(
        self,
        catalog: Catalog,
        layers: Sequence[tuple[str, str]],
        rate_for: Callable[[int, date], Fraction | None],
        add_new: bool,
    ) -> None:
        self.cat = catalog
        self.layers = layers
        self.rate_for = rate_for
        self.add_new = add_new
        self.plan = ImportPlan()
        self.new_index: dict[tuple[int, str, int | None], int] = {}

    def read(self, rows: Sequence[Sequence[str]]) -> ImportPlan:
        rows = [list(r) for r in rows]
        while rows and not any(c.strip() for c in rows[0]):
            rows.pop(0)
        if not rows:
            self.plan.problem = tr("таблица пуста")
            return self.plan
        columns = header(rows[0])
        have = {f for f, pos in columns.values() if pos == 0}
        missing = [REQUIRED_NAMES[f] for f in REQUIRED if f not in have]
        if missing:
            self.plan.problem = tr(
                "в первой строке нужны заголовки колонок; не найдены: {names}",
                names=", ".join(tr(m) for m in missing),
            )
            return self.plan
        groups: dict[str, int] = {}
        postings: list[list[PostingInput]] = []
        for offset, cells in enumerate(rows[1:], start=2):
            if not any(c.strip() for c in cells):
                continue
            values = {
                key: (cells[i].strip() if i < len(cells) else "") for i, key in columns.items()
            }
            key = values.get(("document", 0), "") or f"#row{offset}"
            if key not in groups:
                groups[key] = len(postings)
                postings.append([])
                self.plan.documents.append(ImportedDocument("", [], "", "common"))
            doc_index = groups[key]
            row = Row(offset, doc_index)
            self.plan.rows.append(row)
            posting = self._row(row, values)
            self._document(doc_index, row, values)
            if posting is not None:
                postings[doc_index].append(posting)
        for i, doc in enumerate(self.plan.documents):
            self.plan.documents[i] = ImportedDocument(
                doc.doc_date, postings[i], doc.memo, doc.layer
            )
        return self.plan

    def _document(self, index: int, row: Row, values: dict) -> None:
        doc = self.plan.documents[index]
        first = not self.plan.rows_of(index)[:-1]
        layer = self._layer(row, values.get(("layer", 0), ""))
        day = row.doc_date.isoformat() if row.doc_date else ""
        if first:
            self.plan.documents[index] = ImportedDocument(day, [], row.memo, layer)
            return
        if day and doc.doc_date and day != doc.doc_date:
            row.errors.append(tr("в одном документе разные даты"))

    def _layer(self, row: Row, text: str) -> str:
        if not text:
            return "common"
        needle = fold(text)
        for code, name in self.layers:
            if needle in (fold(code), fold(name)) or fold(name).startswith(needle):
                return code
        row.errors.append(tr("неизвестная книга «{text}»", text=text))
        return "common"

    def _row(self, row: Row, values: dict) -> PostingInput | None:
        text = values.get(("date", 0), "")
        row.doc_date = parse_date(text)
        if row.doc_date is None:
            row.errors.append(tr("дата «{text}» не понята", text=text) if text else tr("нет даты"))
        row.memo = values.get(("memo", 0), "")
        try:
            row.invoice = normalize_invoice(values.get(("invoice", 0), "")) or ""
        except ValidationError as e:
            row.errors.append(str(e))
        accounts = {}
        for side in (DT, CT):
            text = values.get((side, 0), "")
            try:
                accounts[side] = self.cat.resolve_account(text)
            except LookupError as e:
                row.errors.append(str(e).strip("'\""))
        row.debit, row.credit = accounts.get(DT), accounts.get(CT)
        subconto = {
            side: self._subconto(row, side, accounts.get(side), values) for side in (DT, CT)
        }
        amount_text = values.get(("amount", 0), "")
        amount = self._money(row, amount_text, tr("сумма"))
        currency_id, currency_amount = self._currency(row, accounts, subconto, values)
        if amount is None and not amount_text:  # in manat: by the rate, or missing
            if currency_id is not None and currency_amount is not None:
                amount = self._at_rate(row, currency_id, currency_amount, values)
            elif not row.errors:
                row.errors.append(tr("нет суммы"))
        row.amount = amount
        if row.errors or row.debit is None or row.credit is None or amount is None:
            return None
        return PostingInput(
            row.debit.id,
            row.credit.id,
            from_minor(amount),
            subconto[DT],
            subconto[CT],
            row.memo,
            currency_id,
            None if currency_amount is None else from_minor(currency_amount),
            row.invoice,
        )

    def _subconto(
        self, row: Row, side: str, acc: AccountInfo | None, values: dict
    ) -> tuple[int | None, ...]:
        result: list[int | None] = [None, None, None]
        names = row.debit_names if side == DT else row.credit_names
        for pos in (1, 2, 3):
            text = values.get((side, pos), "")
            if not text or acc is None:
                continue
            kind = acc.sc_kinds[pos - 1]
            if kind is None:
                row.errors.append(
                    tr(
                        "у счёта {code} нет субконто {i}: «{text}»",
                        code=acc.short,
                        i=pos,
                        text=text,
                    )
                )
                continue
            owner = self.cat.owner_in(acc, result, pos - 1)
            try:
                value = self.cat.resolve_value(kind, text, owner)  # a new owner: common only
            except LookupError as e:
                row.errors.append(str(e).strip("'\""))
                continue
            if value is not None:
                result[pos - 1] = value
                names.append(self.cat.value(value).name)
            elif self.add_new:
                key = (kind, text, owner if kind in self.cat.owner_kinds else None)
                if key not in self.new_index:
                    self.new_index[key] = len(self.plan.new_values)
                    self.plan.new_values.append(key)
                result[pos - 1] = -(self.new_index[key] + 1)
                names.append(f"+{text}")
            else:
                row.errors.append(
                    tr("«{text}» нет в справочнике «{kind}»", text=text, kind=self.cat.kinds[kind])
                )
        return tuple(result)

    def _money(self, row: Row, text: str, what: str) -> int | None:
        if not text:
            return None
        try:
            value = to_minor(plain_number(text))
        except (ValueError, TypeError):
            row.errors.append(tr("{what}: не число «{text}»", what=what, text=text))
            return None
        if value <= 0:
            row.errors.append(tr("{what} должна быть больше нуля: {text}", what=what, text=text))
            return None
        return value

    def _currency(self, row: Row, accounts: dict, subconto: dict, values: dict):
        code = values.get(("currency", 0), "")
        currency_amount = self._money(
            row, values.get(("currency_amount", 0), ""), tr("сумма в валюте")
        )
        in_currency = any(a is not None and a.currency for a in accounts.values())
        if not in_currency:
            if code or currency_amount is not None:
                row.errors.append(tr("валюта указана, но счета без валютного учёта"))
            return None, None
        currency_id = None
        if code:
            try:
                currency_id = self.cat.resolve_currency(code).id
            except LookupError as e:
                row.errors.append(str(e).strip("'\""))
                return None, None
        else:  # the currency of a chosen element (a USD bank account)
            currency_id = next(
                (
                    self.cat.value(v).currency_id
                    for side in (DT, CT)
                    for v in subconto[side]
                    if v is not None and v > 0 and self.cat.value(v).currency_id is not None
                ),
                None,
            )
        if currency_id is None:
            if currency_amount is None and all(
                a.currency_optional for a in accounts.values() if a is not None and a.currency
            ):
                return None, None  # 60 / 62 in manat
            row.errors.append(tr("счёт в валюте: нет колонки «Валюта» или валюты у элемента"))
            return None, None
        if currency_amount is None:
            row.errors.append(tr("счёт в валюте: нет суммы в колонке «В валюте»"))
            return None, None
        row.currency = self.cat.currencies[currency_id].code
        row.currency_amount = currency_amount
        return currency_id, currency_amount

    def _at_rate(
        self, row: Row, currency_id: int, currency_amount: int, values: dict
    ) -> int | None:
        text = values.get(("rate", 0), "")
        if text:
            try:
                rate = unit_rate(parse_rate(plain_number(text)))
            except (ValueError, TypeError) as e:
                row.errors.append(str(e))
                return None
        else:
            day = row.doc_date or date.today()
            rate = self.rate_for(currency_id, day)
            if rate is None:
                row.errors.append(no_rate_text(row.currency, day))
                return None
        return to_base(currency_amount, rate)


def read_plan(
    rows: Sequence[Sequence[str]],
    catalog: Catalog,
    layers: Sequence[tuple[str, str]] = (("common", ""),),
    rate_for: Callable[[int, date], Fraction | None] = lambda _c, _d: None,
    add_new: bool = False,
) -> ImportPlan:
    return _Reader(catalog, layers, rate_for, add_new).read(rows)


LINE = re.compile(r"^\S+ (\d+)[,:]\s*")  # "строка 2, …" / "sətir 2: …" of the ledger


def _attach(plan: ImportPlan, document: int, message: str) -> None:
    """A ledger problem goes to the row of its posting ("строка 2" = 2nd row of the
    document), without that prefix: the preview numbers rows as in the sheet."""
    rows = plan.rows_of(document)
    if not rows:
        return
    m = LINE.match(message)
    if m and 1 <= int(m[1]) <= len(rows):
        rows[int(m[1]) - 1].errors.append(message[m.end() :])
    else:
        rows[0].errors.append(message)


def check(ledger: Ledger, company_id: int, plan: ImportPlan, post: bool = True) -> None:
    """Let the ledger check the documents whose rows are fine (subconto filled, period
    open…), without writing anything; its problems go to their rows."""
    ready = [i for i in range(len(plan.documents)) if not any(r.errors for r in plan.rows_of(i))]
    outcome = ledger.import_documents(
        company_id,
        [plan.documents[i] for i in ready],
        plan.new_values,
        post=post,
        check_only=True,
    )
    for index, message in outcome.errors:
        _attach(plan, ready[index], message)


def run(ledger: Ledger, company_id: int, plan: ImportPlan, post: bool = True) -> list[int]:
    """Write all documents of a plan without problems; returns their ids ([] if refused)."""
    if plan.errors or not plan.documents:
        return []
    outcome = ledger.import_documents(company_id, plan.documents, plan.new_values, post=post)
    for index, message in outcome.errors:
        _attach(plan, index, message)
    return outcome.ids
