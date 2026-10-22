"""What Ctrl+K offers (D86): commands, places and reports of the sidebar, accounts,
counterparties and documents — each with what Enter does. The places come from the
sidebar's sections, so a module's place is found as soon as it is in the sidebar."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from modern_gl.application.queries import find_documents
from modern_gl.desktop.command_palette import Entry, matches
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.main_window.sidebar import sections
from modern_gl.desktop.reports_page import month_of
from modern_gl.desktop.widgets import ru_date
from modern_gl.i18n import tr
from modern_gl.reporting.trade import PURCHASE, SALE

if TYPE_CHECKING:
    from modern_gl.desktop.main_window.window import MainWindow

FOUND = 6  # rows of a group while searching: the best few, not a list to scroll
REPORT_SECTION = "Отчёты"


def palette_entries(win: MainWindow, query: str) -> list[Entry]:
    """The palette's rows for what is typed: with nothing typed — commands and places."""
    s = win.session
    if s is None:
        return []
    found = [e for e in _commands(win) + _places(win) if matches(e, query)]
    if not query.strip():
        return found
    if not s.stock_only:
        found += _accounts(win, query)
    found += _counterparties(win, query)
    if not s.stock_only:
        found += _documents(win, query)
    return found


def _commands(win: MainWindow) -> list[Entry]:
    s = win.open_session
    group = tr("Команды")
    items: list[tuple[str, Callable[[], None], str, str]] = []
    if not s.read_only:
        if not s.stock_only:
            items += [
                (tr("Новый документ"), win.new_document, "Ctrl+N", "new"),
                (tr("Быстрая строка"), win.quick_entry, "Ctrl+L", "journal"),
            ]
        items += [
            (tr("Новая покупка"), lambda: win.new_inventory_document(PURCHASE), "", "purchases"),
            (tr("Новая продажа"), lambda: win.new_inventory_document(SALE), "", "sales"),
        ]
        if not s.stock_only:
            items += [
                (tr("Новая банковская операция"), win.new_bank_operation, "", "bank"),
                (tr("Импорт проводок из Excel"), win.show_import, "", "import"),
                (tr("Закрытие периода…"), win.close_period, "", "lock"),
            ]
    return [Entry(group, title, run, hint, icon) for title, run, hint, icon in items]


def _places(win: MainWindow) -> list[Entry]:
    entries = []
    for heading, places in sections(win.open_session.stock_only):
        group = tr("Отчёты") if heading == REPORT_SECTION else tr("Разделы")
        for key, text in places:
            entries.append(Entry(group, tr(text), lambda key=key: win.show_place(key), icon=key[0]))
    entries.append(
        Entry(
            tr("Отчёты"),
            tr("Доп. расходы по декларациям"),
            win.open_landed_report,
            icon="report",
        )
    )
    if win.open_session.parallel_books:  # D98
        entries.append(Entry(tr("Отчёты"), tr("Сравнение книг"), win.open_books, icon="books"))
    # the places first, then the reports: one heading for each
    return sorted(entries, key=lambda e: e.group == tr("Отчёты"))


def _accounts(win: MainWindow, query: str) -> list[Entry]:
    s = win.open_session
    group, card = tr("Счета"), tr("Карточка счёта")
    found = []
    for account in s.catalog.accounts.values():
        entry = Entry(
            group,
            account.label,
            lambda a=account.id: win.open_report("card", a, month_of(s.working_date)),
            card,
            "account",
            account.code,
        )
        if account.active and matches(entry, query):
            found.append(entry)
    found.sort(key=lambda e: (not code_first(e.words, query), e.words))
    return found[:FOUND]


def _counterparties(win: MainWindow, query: str) -> list[Entry]:
    cat = win.open_session.catalog
    group = tr("Контрагенты")
    found = []
    for kind_id in cat.kinds:
        if not cat.has_tax_id(kind_id):
            continue
        for value in cat.values(kind_id):
            entry = Entry(
                group,
                value.name,
                lambda k=kind_id, v=value.id: show_value(win, k, v),
                value.tax_id or "",
                "counterparty",
                value.tax_id or "",
            )
            if not value.is_group and matches(entry, query):
                found.append(entry)
    return found[:FOUND]


def _documents(win: MainWindow, query: str) -> list[Entry]:
    s = win.open_session
    group = tr("Документы")
    return [
        Entry(
            group,
            f"№{d.number}  {d.memo}".rstrip(),
            lambda doc_id=d.id: win.open_document(doc_id),
            ru_date(d.doc_date) + ("" if d.status == "posted" else f" · {tr('Черновик')}"),
            "document",
        )
        for d in find_documents(s.conn, s.company_id, query, FOUND)
    ]


def code_first(code: str, query: str) -> bool:
    """An account whose code starts with what is typed comes first («60» → 60, 60.1…)."""
    return bool(code) and code.startswith(query.strip())


def show_value(win: MainWindow, kind_id: int, value_id: int) -> None:
    """A counterparty from Ctrl+K: its directory, with it chosen."""
    win.show_place(("directories",))
    page = win.pages.get(("directories",))
    if isinstance(page, DirectoriesPage):
        page.refresh(select_kind=kind_id)
        page.refresh_values(select_value=value_id)
        page.focus_table()
