"""Every report of the program in one list (D114): its group, name, one line of what it
shows and its icon — the page «Отчёты», the sidebar's pinned reports and Ctrl+K read it.

What is pinned and what was opened lately is the user's, kept in `QSettings` (like the
zebra, D103): the same for every company, nothing is written to a company's file."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.desktop.preferences import PINNED_REPORTS, RECENT_REPORTS, prefs
from modern_gl.i18n import N_, fold
from modern_gl.i18n_az import AZ

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
    N_("Финансовая отчётность"),
    N_("Бухгалтерские"),
    N_("Налоги и e-qaimə"),
    N_("Склад"),
    N_("Банк"),
)
REPORTS = (
    Report(
        "balance",
        GROUPS[0],
        N_("Баланс"),
        N_("Активы, обязательства и капитал на конец периода"),
        "statements",
    ),
    Report(
        "profit",
        GROUPS[0],
        N_("Прибыли и убытки"),
        N_("Выручка, расходы и прибыль за период"),
        "profit",
    ),
    Report(
        "cash",
        GROUPS[0],
        N_("Движение денег"),
        N_("Поступления и выплаты по видам деятельности"),
        "cash",
    ),
    Report("osv", GROUPS[1], N_("ОСВ"), N_("Остатки и обороты всех счетов за период"), "osv"),
    Report(
        "subconto",
        GROUPS[1],
        N_("ОСВ по субконто"),
        N_("Остатки счёта по контрагентам, договорам, статьям"),
        "subconto",
    ),
    Report(
        "card", GROUPS[1], N_("Карточка счёта"), N_("Проводки счёта за период с остатком"), "card"
    ),
    Report(
        "analysis",
        GROUPS[1],
        N_("Анализ счёта"),
        N_("Обороты счёта по корреспондирующим счетам"),
        "analysis",
    ),
    Report(
        "subconto_analysis",
        GROUPS[1],
        N_("Анализ субконто"),
        N_("Контрагент, заказ или проект по всем счетам сразу"),
        "directories",
    ),
    Report(
        "reconciliation_act",
        GROUPS[1],
        N_("Акт сверки"),
        N_("Расчёты с контрагентом за период, акт для подписи в Excel — одному или всем"),
        "counterparty",
    ),
    Report(
        "books",
        GROUPS[1],
        N_("Сравнение книг"),
        N_("Общий учёт, МСФО и налоговый учёт на одну дату"),
        "books",
        parallel=True,
    ),
    Report(
        "handover",
        GROUPS[1],
        N_("Передача дел"),
        N_("Всё о компании текстом в одном архиве zip"),
        "archive",
    ),
    Report(
        "action_log",
        GROUPS[1],
        N_("Журнал действий"),
        N_("Кто открывал компанию, что вводил, проводил, исправлял и удалял"),
        "history",
        books=False,
    ),
    Report(
        "invoices",
        GROUPS[2],
        "E-qaimələr",
        N_("Проводки периода по номерам e-qaimə: суммы, ƏDV, остаток"),
        "invoices",
    ),
    Report(
        "vat_register",
        GROUPS[2],
        N_("Реестр e-qaimə"),
        N_("Покупки и продажи периода для декларации ƏDV: суммы, ƏDV, оплата; итоги по ставкам"),
        "invoices",
    ),
    Report(
        "vat_liability",
        GROUPS[2],
        N_("ƏDV продаж к уплате"),
        N_("ƏDV продаж по дням поступления денег, аванс тоже: e-qaimə, ƏDV на депозит"),
        "invoices",
    ),
    Report(
        "vat_receipts",
        GROUPS[2],
        N_("Поступления и e-qaimə"),
        N_("Сверка по покупателям: деньги с номером и без, e-qaimə, ƏDV, аванс, неоплаченное"),
        "invoices",
    ),
    Report(
        "vat_payments",
        GROUPS[2],
        N_("Оплаты поставщикам и e-qaimə"),
        N_("Сверка по поставщикам: оплаты с номером и без, e-qaimə, зачёт ƏDV, аванс"),
        "invoices",
    ),
    Report(
        "vat_credit",
        GROUPS[2],
        N_("ƏDV к зачёту"),
        N_("Зачёт ƏDV покупок по дням: e-qaimə, оплата суммы и ƏDV; декларации — по оплате ƏDV"),
        "invoices",
    ),
    Report(
        "reconcile_purchases",
        GROUPS[2],
        N_("Сверка покупок с порталом"),
        N_("E-qaimə портала против проведённых покупок"),
        "reconcile",
        books=False,
        writes=True,
    ),
    Report(
        "reconcile_sales",
        GROUPS[2],
        N_("Сверка продаж с порталом"),
        N_("E-qaimə портала против проведённых продаж"),
        "reconcile",
        books=False,
        writes=True,
    ),
    Report(
        "stock",
        GROUPS[3],
        N_("Остатки товаров"),
        N_("Остатки, движения и документы склада"),
        "inventory",
        books=False,
    ),
    Report(
        "stock_statement",
        GROUPS[3],
        N_("Ведомость по складу"),
        N_("Остаток на начало, приход, расход и остаток на конец — количество и сумма"),
        "osv",
        books=False,
    ),
    Report(
        "gross_profit",
        GROUPS[3],
        N_("Валовая прибыль по товарам"),
        N_("Продано, выручка, себестоимость и прибыль — по товарам или покупателям"),
        "profit",
        books=False,
    ),
    Report(
        "landed",
        GROUPS[3],
        N_("Дополнительные расходы"),
        N_("Таможня, доставка и другие расходы, вошедшие в стоимость товара"),
        "landed",
        books=False,
    ),
    Report(
        "bank",
        GROUPS[4],
        N_("Остатки на счетах"),
        N_("Банковские счета, выписки по дням и сверка"),
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
    ids = prefs().report_ids(key)
    return list(default) if ids is None else [i for i in ids if i in BY_ID]


def pinned() -> list[str]:
    """The pinned reports in the order they were pinned (the sidebar shows them so)."""
    return list(dict.fromkeys(_ids(PINNED_REPORTS, DEFAULT_PINNED)))


def set_pinned(report_id: str, on: bool) -> None:
    ids = [i for i in pinned() if i != report_id] + ([report_id] if on else [])
    prefs().set_report_ids(PINNED_REPORTS, ids)


def recent() -> list[str]:
    """The reports opened lately, the last first."""
    return _ids(RECENT_REPORTS, ())[:RECENT_SHOWN]


def remember(report_id: str) -> None:
    ids = [report_id] + [i for i in recent() if i != report_id]
    prefs().set_report_ids(RECENT_REPORTS, ids[:RECENT_SHOWN])
