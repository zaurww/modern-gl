"""Every report of the program in one list (D114): its group, name, one line of what it
shows and its icon — the page «Отчёты», the sidebar's pinned reports and Ctrl+K read it.

What is pinned and what was opened lately is the user's, kept in `QSettings` (like the
zebra, D103): the same for every company, nothing is written to a company's file."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from modern_gl.i18n import fold
from modern_gl.i18n_az import AZ

PINNED_SETTING, RECENT_SETTING = "reports/pinned", "reports/recent"
# what the sidebar showed before the catalog: kept there until the user changes it
DEFAULT_PINNED = ("osv", "balance", "profit")
RECENT_SHOWN = 5
HUB = ("reports",)  # the sidebar's place «Все отчёты»


@dataclass(frozen=True)
class Report:
    id: str
    group: str  # Russian, translated on display
    title: str
    hint: str
    icon: str  # a name of `desktop/icons.GLYPHS`
    books: bool = True  # a report of the books: not in a warehouse-only company (D90)
    writes: bool = False  # it may make documents: not while viewing (D80)
    parallel: bool = False  # only with the parallel books on (D63)


GROUPS = (
    "Финансовая отчётность",
    "Бухгалтерские",
    "Налоги и e-qaimə",
    "Склад",
    "Банк",
)
REPORTS = (
    Report(
        "balance",
        GROUPS[0],
        "Баланс",
        "Активы, обязательства и капитал на конец периода",
        "statements",
    ),
    Report(
        "profit",
        GROUPS[0],
        "Прибыли и убытки",
        "Выручка, расходы и прибыль за период",
        "profit",
    ),
    Report(
        "cash",
        GROUPS[0],
        "Движение денег",
        "Поступления и выплаты по видам деятельности",
        "cash",
    ),
    Report("osv", GROUPS[1], "ОСВ", "Остатки и обороты всех счетов за период", "osv"),
    Report(
        "subconto",
        GROUPS[1],
        "ОСВ по субконто",
        "Остатки счёта по контрагентам, договорам, статьям",
        "subconto",
    ),
    Report("card", GROUPS[1], "Карточка счёта", "Проводки счёта за период с остатком", "card"),
    Report(
        "analysis",
        GROUPS[1],
        "Анализ счёта",
        "Обороты счёта по корреспондирующим счетам",
        "analysis",
    ),
    Report(
        "subconto_analysis",
        GROUPS[1],
        "Анализ субконто",
        "Контрагент, заказ или проект по всем счетам сразу",
        "directories",
    ),
    Report(
        "books",
        GROUPS[1],
        "Сравнение книг",
        "Общий учёт, МСФО и налоговый учёт на одну дату",
        "books",
        parallel=True,
    ),
    Report(
        "handover",
        GROUPS[1],
        "Передача дел",
        "Всё о компании текстом в одном архиве zip",
        "archive",
    ),
    Report(
        "invoices",
        GROUPS[2],
        "E-qaimələr",
        "Проводки периода по номерам e-qaimə: суммы, ƏDV, остаток",
        "invoices",
    ),
    Report(
        "vat_credit",
        GROUPS[2],
        "ƏDV к зачёту",
        "Зачёт ƏDV покупок по дням: e-qaimə, оплата суммы и ƏDV; декларации — по оплате ƏDV",
        "invoices",
    ),
    Report(
        "reconcile_purchases",
        GROUPS[2],
        "Сверка покупок с порталом",
        "E-qaimə портала против проведённых покупок",
        "reconcile",
        books=False,
        writes=True,
    ),
    Report(
        "reconcile_sales",
        GROUPS[2],
        "Сверка продаж с порталом",
        "E-qaimə портала против проведённых продаж",
        "reconcile",
        books=False,
        writes=True,
    ),
    Report(
        "landed",
        GROUPS[2],
        "Доп. расходы по декларациям",
        "Таможня и доставка импорта по декларациям",
        "landed",
        books=False,
    ),
    Report(
        "stock",
        GROUPS[3],
        "Остатки товаров",
        "Остатки, движения и документы склада",
        "inventory",
        books=False,
    ),
    Report(
        "bank",
        GROUPS[4],
        "Остатки на счетах",
        "Банковские счета, выписки по дням и сверка",
        "bank",
    ),
)
BY_ID = {r.id: r for r in REPORTS}
# the sidebar's key of a pinned report: a report that is a place of its own keeps the
# place's key (its page is chosen in the sidebar when shown); a view of the statements —
# the view's; the others ask something or open a page of their own
PLACE_OF = {"osv": ("osv",), "invoices": ("invoices",)}
VIEW_OF = {"balance": "balance", "profit": "profit", "cash": "cash"}


def pin_key(report_id: str) -> tuple:
    if report_id in PLACE_OF:
        return PLACE_OF[report_id]
    if report_id in VIEW_OF:
        return ("statements", VIEW_OF[report_id])
    return ("pin", report_id)


PIN_KEYS = {pin_key(r.id): r.id for r in REPORTS}


def shown(stock_only: bool, read_only: bool, parallel_books: bool) -> list[Report]:
    """The reports a company of this mode has, in the catalog's order."""
    return [
        r
        for r in REPORTS
        if not (stock_only and r.books)
        and not (read_only and r.writes)
        and (parallel_books or not r.parallel)
    ]


def names(report: Report) -> str:
    """The report's name in both languages: found by either, whatever the interface."""
    return f"{report.title} {AZ.get(report.title, '')}".strip()


def matches(report: Report, query: str) -> bool:
    """Every word typed is in the name, the line under it or the group — in Russian or
    in Azerbaijani, letters folded (ə = e, ş = s)."""
    words = fold(query).split()
    if not words:
        return True
    said = (report.title, report.hint, report.group)
    text = fold(" ".join(said + tuple(AZ.get(t, t) for t in said)))
    return all(word in text for word in words)


def _ids(key: str, default: tuple[str, ...]) -> list[str]:
    value = QSettings().value(key)
    if value is None:
        return list(default)
    return [i for i in str(value).split(",") if i in BY_ID]


def pinned() -> list[str]:
    """The pinned reports in the order they were pinned (the sidebar shows them so)."""
    return list(dict.fromkeys(_ids(PINNED_SETTING, DEFAULT_PINNED)))


def set_pinned(report_id: str, on: bool) -> None:
    ids = [i for i in pinned() if i != report_id] + ([report_id] if on else [])
    QSettings().setValue(PINNED_SETTING, ",".join(ids))


def recent() -> list[str]:
    """The reports opened lately, the last first."""
    return _ids(RECENT_SETTING, ())[:RECENT_SHOWN]


def remember(report_id: str) -> None:
    ids = [report_id] + [i for i in recent() if i != report_id]
    QSettings().setValue(RECENT_SETTING, ",".join(ids[:RECENT_SHOWN]))
