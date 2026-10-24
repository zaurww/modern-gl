"""Handing a company over to another accountant (D81): everything as plain text in a zip.

The journal of each book (hledger format, D79), the ОСВ of the current year, the
directories with VÖEN, the currency rates and a README that says how to read them. Like
the journal itself, the package is derived: it is rebuilt from the database each time.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from pathlib import Path

from modern_gl.application.books import BOOKS, COMMON
from modern_gl.domain.currency import format_rate
from modern_gl.domain.dates import iso_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.plaintext import BASE, hledger_journal
from modern_gl.reporting.report_common import Turnovers
from modern_gl.reporting.reports import trial_balance


def handover_files(conn: Connection, company_id: int, as_of: date | str) -> dict[str, str]:
    """File name -> text of the package. Takes every posted document, also a later-dated one."""
    company = conn.execute(
        "SELECT name, parallel_books FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    first, last, count = conn.execute(
        "SELECT MIN(doc_date), MAX(doc_date), COUNT(*) FROM documents "
        "WHERE company_id = ? AND status = 'posted'",
        (company_id,),
    ).fetchone()
    date_to = max(iso_date(as_of), last or "")
    year_start = date_to[:4] + "-01-01"
    books = BOOKS if company["parallel_books"] else {"common": COMMON}
    files: dict[str, str] = {}
    for key, layers in books.items():
        files[f"{key}.journal"] = hledger_journal(conn, company_id, date_to, layers, as_of)
        files[f"osv-{key}.txt"] = osv_text(conn, company_id, year_start, date_to, layers)
    files["directories.csv"] = directories_csv(conn, company_id)
    rates = rates_journal(conn, company_id)
    if rates:
        files["rates.journal"] = rates
    readme = tr(
        "{company}\n"
        "Передача дел — выгружено {today} из Modern GL\n"
        "Проведённых документов: {count}, с {first} по {last}\n\n"
        "Что внутри\n{contents}\n\n"
        "Как читать\n"
        "Все файлы — обычный текст (UTF-8). Журнал — двойная запись в формате hledger\n"
        "(hledger.org): документ — транзакция «дата (номер) содержание», под ней\n"
        "счета Дт (+) и Кт (−). Суммы в манатах, как в ОСВ; сумма в валюте, субконто\n"
        "и номер e-qaimə — в комментарии после «;».\n\n"
        "  hledger -f common.journal bs        баланс\n"
        "  hledger -f common.journal is        прибыли и убытки\n"
        "  hledger -f common.journal bal       сальдо по счетам — совпадает с ОСВ\n"
        "  hledger -f common.journal reg 60    карточка счёта 60\n",
        company=company["name"],
        today=iso_date(as_of),
        count=count,
        first=first or "—",
        last=last or "—",
        contents=_contents(files, year_start, date_to),
    )
    return {"README.txt": readme, **files}


def write_handover(path: Path, files: dict[str, str]) -> None:
    """The zip, whole or not at all: written beside the target, then renamed."""
    part = path.with_name(path.name + ".part")
    folder = path.stem
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name, text in files.items():
                encoding = "utf-8-sig" if name.endswith(".csv") else "utf-8"  # Excel
                z.writestr(f"{folder}/{name}", text.encode(encoding))
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def _contents(files: dict[str, str], start: str, date_to: str) -> str:
    book_names = {"common": tr("Общий учёт"), "ifrs": tr("МСФО"), "tax": tr("Налоговый учёт")}
    lines = []
    for name in files:
        key = name.removesuffix(".journal").removeprefix("osv-").removesuffix(".txt")
        if name.endswith(".journal") and key in BOOKS:
            text = tr("все проводки — книга «{book}»", book=book_names[key])
        elif name.startswith("osv-"):
            text = tr(
                "ОСВ с {start} по {date} — книга «{book}»",
                start=start,
                date=date_to,
                book=book_names[key],
            )
        elif name == "directories.csv":
            text = tr("справочники: контрагенты с VÖEN, банковские счета, договоры…")
        else:
            text = tr("курсы валют")
        lines.append(f"  {name:<18}{text}")
    return "\n".join(lines)


def osv_text(conn: Connection, company_id: int, date_from: str, date_to: str, layers) -> str:
    """The ОСВ as a fixed-width table: opening, turnovers and closing, Dt and Ct."""
    osv = trial_balance(conn, company_id, date_from, date_to, layers)
    labels = [("  " * r.depth + " ".join(filter(None, (r.code, r.name))), r) for r in osv.rows]
    labels = [(label, r) for label, r in labels if not r.is_zero()]
    width = max([len(label) for label, _ in labels] + [len(tr("Итого"))])
    columns = (
        tr("Сальдо нач. Дт"),
        tr("Сальдо нач. Кт"),
        tr("Оборот Дт"),
        tr("Оборот Кт"),
        tr("Сальдо кон. Дт"),
        tr("Сальдо кон. Кт"),
    )
    title = tr("Оборотно-сальдовая ведомость с {start} по {end}", start=date_from, end=date_to)
    head = f"{tr('Счёт'):<{width}}" + "".join(f"{c:>16}" for c in columns)
    out = [title, f"{tr('Суммы в {currency}', currency=BASE)}", "", head, "-" * len(head)]
    out += [f"{label:<{width}}{_figures(r)}" for label, r in labels]
    out += ["-" * len(head), f"{tr('Итого'):<{width}}{_figures(osv.total)}"]
    return "\n".join(out) + "\n"


def _figures(t: Turnovers) -> str:
    values = (t.opening_dt, t.opening_ct, t.turnover_dt, t.turnover_ct, t.closing_dt, t.closing_ct)
    return "".join(f"{format_minor(v) if v else '—':>16}" for v in values)


def directories_csv(conn: Connection, company_id: int) -> str:
    rows = conn.execute(
        """
        SELECT k.name AS kind, v.code, v.name, v.legal_name, v.tax_id, v.country,
               c.code AS currency, v.active
        FROM subconto_values v
        JOIN subconto_kinds k ON k.id = v.kind_id
        LEFT JOIN currencies c ON c.id = v.currency_id
        WHERE v.company_id = ?
        ORDER BY k.name, v.name, v.id
        """,
        (company_id,),
    )
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(
        [
            tr("Вид"),
            tr("Код"),
            tr("Название"),
            tr("Юридическое название"),
            "VÖEN",
            tr("Страна"),
            tr("Валюта"),
            tr("Активен"),
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["kind"],
                r["code"] or "",
                r["name"],
                r["legal_name"] or "",
                r["tax_id"] or "",
                r["country"] or "",
                r["currency"] or "",
                tr("да") if r["active"] else tr("нет"),
            ]
        )
    return out.getvalue()


def rates_journal(conn: Connection, company_id: int) -> str:
    """Currency rates as hledger price directives: «P 2026-03-01 USD 1.7000 AZN»; "" if none."""
    rows = conn.execute(
        """
        SELECT r.rate_date, c.code, r.rate, r.nominal
        FROM currency_rates r JOIN currencies c ON c.id = r.currency_id
        WHERE r.company_id = ?
        ORDER BY r.rate_date, c.code
        """,
        (company_id,),
    )
    lines = [
        f"P {r['rate_date']} {r['code']} {format_rate(r['rate'], r['nominal'])} {BASE}"
        for r in rows
    ]
    return "\n".join([f"; {tr('курсы валют')}", *lines]) + "\n" if lines else ""
