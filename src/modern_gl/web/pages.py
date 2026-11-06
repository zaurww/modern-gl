"""The report pages: what `reporting.answers` says, as HTML. Each function only reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from modern_gl.application.books import BOOKS
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import answers
from modern_gl.web.layout import company_path, esc, link, num, page, sidebar


def book_names() -> dict[str, str]:
    return {"common": tr("Общий учёт"), "ifrs": tr("МСФО"), "tax": tr("Налоговый учёт")}


@dataclass(frozen=True)
class View:
    """One request to a company: which one, for what period, in which book."""

    conn: Connection
    company_id: int
    company: str
    many: bool  # there are other companies to go back to
    date_from: str
    date_to: str
    book: str
    books: bool  # the company keeps parallel books
    search: str = ""

    @property
    def period(self) -> dict[str, str]:
        return {"from": self.date_from, "to": self.date_to, "book": self.book}

    @property
    def about(self) -> str:
        return f"{self.date_from} — {self.date_to}"


def iso_date(text: str, default: str) -> str:
    """A date of the address; anything else — the default."""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return default


def book_of(text: str) -> str:
    return text if text in BOOKS else "common"


def _year_step(view: View, step: int, page_name: str, label: str, keep: Mapping) -> str:
    year = int(view.date_from[:4]) + step
    period = {"from": f"{year}-01-01", "to": f"{year}-12-31", "book": view.book}
    return link(company_path(view.company, page_name, **period, **keep), label, "step")


def _book_field(view: View, page_name: str) -> str:
    if not view.books or page_name == "journal":  # the journal lists every book's documents
        return f'<input type="hidden" name="book" value="{esc(view.book)}">'
    options = "".join(
        f'<option value="{code}"{" selected" if code == view.book else ""}>{esc(name)}</option>'
        for code, name in book_names().items()
    )
    return f'<select name="book" data-auto aria-label="{esc(tr("Книга"))}">{options}</select>'


def _bar(view: View, page_name: str, keep: Mapping[str, str] | None = None) -> str:
    """The period, the book, what else the page keeps; a change shows at once (D127)."""
    keep = keep or {}
    hidden = "".join(
        f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in keep.items()
    )
    search = ""
    if page_name == "journal":
        search = (
            f'<input class="search" type="search" name="q" value="{esc(view.search)}" '
            f'placeholder="{esc(tr("Поиск"))}" data-auto>'
        )
    return (
        f'<form class="bar" method="get">{_year_step(view, -1, page_name, "‹", keep)}'
        f'<input type="date" name="from" value="{esc(view.date_from)}" data-auto '
        f'aria-label="{esc(tr("Период"))}">'
        f'<input type="date" name="to" value="{esc(view.date_to)}" data-auto '
        f'aria-label="{esc(tr("Период"))}">'
        f"{_year_step(view, 1, page_name, '›', keep)}{_book_field(view, page_name)}"
        f"{search}{hidden}</form>"
    )


def _shell(view: View, current: str, title: str, subtitle: str, body: str) -> str:
    return page(title, subtitle, body, sidebar(view.company, current, view.many, view.period))


def _head(columns: tuple[tuple[str, str], ...]) -> str:
    return "".join(f'<th class="{css}">{esc(name)}</th>' for name, css in columns)


def _table(head: str, rows: str) -> str:
    return f'<div class="wrap"><table class="full"><tr>{head}</tr>{rows}</table></div>'


def _left_out(count: int) -> str:
    if not count:
        return ""
    text = tr("Ещё {n} строк не показано — выберите период короче", n=count)
    return f'<p class="note">{esc(text)}</p>'


def _nothing() -> str:
    return f'<p class="empty">{esc(tr("Нет данных"))}</p>'


def trial_balance(view: View) -> str:
    osv = answers.trial_balance(view.conn, view.company_id, view.date_from, view.date_to, view.book)
    title = tr("Оборотно-сальдовая ведомость")
    if not osv["rows"]:
        return _shell(view, "osv", title, view.about, _bar(view, "osv") + _nothing())
    groups = (tr("Сальдо на начало"), tr("Обороты"), tr("Сальдо на конец"))
    pair = f'<th class="num">{esc(tr("Дт"))}</th><th class="num">{esc(tr("Кт"))}</th>'
    head = (
        f'<tr><th rowspan="2">{esc(tr("Счёт"))}</th>'
        + "".join(f'<th class="group" colspan="2">{esc(name)}</th>' for name in groups)
        + f"</tr><tr>{pair * 3}</tr>"
    )
    rows = "".join(_osv_row(view, r) for r in osv["rows"])
    rows += f'<tr class="total"><td>{esc(tr("Итого"))}</td>{_pairs(osv["total"])}</tr>'
    table = f'<div class="wrap"><table>{head}{rows}</table></div>'
    return _shell(view, "osv", title, view.about, _bar(view, "osv") + _osv_check(osv) + table)


def _pairs(row: Mapping) -> str:
    return "".join(
        num(row[part]["debit"]) + num(row[part]["credit"])
        for part in ("opening", "turnover", "closing")
    )


def _osv_row(view: View, row: Mapping) -> str:
    label = " ".join(part for part in (row["code"], row["name"]) if part)
    name = esc(label)
    if row["code"]:
        name = link(company_path(view.company, "card", account=row["code"], **view.period), label)
    css = "group" if row["group"] else "sub" if row["depth"] else ""
    return (
        f'<tr class="{css}"><td>{"&nbsp;&nbsp;&nbsp;" * row["depth"]}{name}</td>{_pairs(row)}</tr>'
    )


def _osv_check(osv: Mapping) -> str:
    closing = osv["total"]["closing"]
    if closing["debit"] != closing["credit"]:
        return f'<p class="check bad">{esc(tr("Дебет и кредит не сходятся"))}</p>'
    return f'<p class="check ok">{esc(tr("Дебет и кредит сходятся  ✓"))}</p>'


def account_card(view: View, account: str) -> str:
    card = answers.account_card(
        view.conn, view.company_id, account, view.date_from, view.date_to, view.book
    )
    head = _head(
        (
            (tr("Дата"), ""),
            (tr("№"), ""),
            (tr("Содержание"), ""),
            (tr("Корр. счёт"), ""),
            (tr("Дт"), "num"),
            (tr("Кт"), "num"),
            (tr("Сальдо"), "num"),
        )
    )
    first = f'<td colspan="6">{esc(tr("Сальдо на начало"))}</td>{num(card["opening_balance"])}'
    last = f'<td colspan="6">{esc(tr("Сальдо на конец"))}</td>{num(card["closing_balance"])}'
    lines = "".join(_card_row(view, line) for line in card["lines"])
    table = _table(head, f'<tr class="group">{first}</tr>{lines}<tr class="total">{last}</tr>')
    body = _bar(view, "card", {"account": account}) + table + _left_out(card["left_out"])
    return _shell(view, "osv", f"{tr('Карточка счёта')} {account}", view.about, body)


def _card_row(view: View, line: Mapping) -> str:
    number = link(company_path(view.company, f"doc/{line['document']}"), line["document"], "link")
    return (
        f"<tr><td>{esc(line['date'])}</td><td>{number}</td><td>{esc(line['memo'])}</td>"
        f"<td>{esc(line['corr_account'])}</td>{num(line['debit'])}{num(line['credit'])}"
        f"{num(line['balance'])}</tr>"
    )


def journal(view: View) -> str:
    found = answers.documents(view.conn, view.company_id, view.date_from, view.date_to, view.search)
    head = _head(
        (
            (tr("№"), ""),
            (tr("Дата"), ""),
            (tr("Содержание"), ""),
            (tr("Статус"), ""),
            (tr("Сумма"), "num"),
        )
    )
    rows = "".join(_journal_row(view, d) for d in found["documents"])
    table = _table(head, rows) if rows else _nothing()
    body = _bar(view, "journal") + table + _left_out(found["left_out"])
    return _shell(view, "journal", tr("Журнал"), view.about, body)


def _journal_row(view: View, doc: Mapping) -> str:
    number = link(company_path(view.company, f"doc/{doc['number']}"), doc["number"], "link")
    dot = '<span class="dot">● </span>' if doc["draft"] else ""
    return (
        f'<tr class="{"" if doc["draft"] else "done"}"><td>{number}</td>'
        f"<td>{esc(doc['date'])}</td><td>{esc(doc['memo'])}</td>"
        f"<td>{dot}{esc(doc['status'])}</td>{num(doc['total'])}</tr>"
    )


def document(view: View, number: int) -> str:
    doc = answers.document(view.conn, view.company_id, number)
    head = _head(
        (
            (tr("Дебет"), ""),
            (tr("Кредит"), ""),
            (tr("Содержание"), ""),
            (tr("Сумма"), "num"),
        )
    )
    rows = "".join(
        f"<tr><td>{_side(p['debit'])}</td><td>{_side(p['credit'])}</td>"
        f"<td>{esc(p['memo'])}</td>{num(p['amount'])}</tr>"
        for p in doc["postings"]
    )
    title = f"{tr('Документ')} №{doc['number']}"
    subtitle = " · ".join(part for part in (doc["date"], doc["memo"]) if part)
    return _shell(view, "journal", title, subtitle, _table(head, rows))


def _side(side: Mapping) -> str:
    return esc(" · ".join([side["account"], *side["subconto"]]))


def companies(names: list[str]) -> str:
    if not names:
        body = f'<p class="empty">{esc(tr("Нет файлов компаний в этой папке"))}</p>'
    else:
        items = "".join(link(company_path(name, "osv"), name) for name in names)
        body = f'<div class="list">{items}</div>'
    return page(tr("Все компании"), tr("Только просмотр"), body)


def problem(message: str) -> str:
    return page(tr("Не удалось показать страницу"), message, link("/", tr("Все компании")))
