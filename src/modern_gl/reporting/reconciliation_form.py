"""The act of reconciliation as the counterparty signs it (üzləşmə aktı): the words of
the form in the company's language of documents (D152), the figures of
`reports.reconciliation_act` on both sides — the counterparty's columns are ours
mirrored (our debit is their credit), as 1C fills them; the partner corrects what
differs. The sheet itself is written by `infrastructure.act_file`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import N_, trd
from modern_gl.infrastructure.act_file import ActRow, ActSheet
from modern_gl.reporting.reports.reconciliation import Party, ReconciliationAct

# said by `trd` in the form and by `tr` on the page
NO_DEBT = N_("На {date} задолженности нет")
DEBT = N_("На {date} задолженность в пользу {name}: {amount} {currency}")


def act_sheet(act: ReconciliationAct) -> ActSheet:
    start, end = _dmy(act.date_from), _dmy(act.date_to)
    return ActSheet(
        title=trd("Акт сверки взаимных расчётов"),
        heading=[
            trd("между {a} и {b}", a=_named(act.company), b=_named(act.partner)),
            trd("за период с {start} по {end}", start=start, end=end),
        ],
        sides=(
            trd("По данным {name}", name=act.company.title),
            trd("По данным {name}", name=act.partner.title),
        ),
        columns=[
            "№",
            trd("Дата"),
            trd("Документ"),
            trd("Дебет"),
            trd("Кредит"),
            trd("Дебет"),
            trd("Кредит"),
        ],
        rows=_rows(act),
        summary=[debt_text(act)],
        signatures=(_signature(act.company), _signature(act.partner)),
    )


def debt_text(act: ReconciliationAct, say: Callable[..., str] = trd) -> str:
    """«На 31.12.2026 задолженность в пользу X: 1 200,00 AZN» — the line both sides
    read first; our debit balance is a debt to us, a credit balance — to the partner.
    `say` — `trd` in the form, `tr` on the page."""
    end = _dmy(act.date_to)
    if act.closing == 0:
        return say(NO_DEBT, date=end)
    owed_to = act.company if act.closing > 0 else act.partner
    return say(
        DEBT,
        date=end,
        name=owed_to.title,
        amount=format_minor(abs(act.closing)),
        currency=act.currency,
    )


def act_file_name(act: ReconciliationAct) -> str:
    """«Üzləşmə aktı — Alfa MMC 01.01-31.12.2026»: the file saved for the partner."""
    return (
        f"{trd('Акт сверки')} — {act.partner.name}"
        f" {act.date_from:%d.%m}-{act.date_to:%d.%m.%Y}.xlsx"
    )


def _rows(act: ReconciliationAct) -> list[ActRow]:
    rows = [_balance_row(trd("Сальдо на начало"), act.opening)]
    for i, ln in enumerate(act.lines, start=1):
        text = ln.memo or trd("Документ № {number}", number=ln.number)
        if ln.invoice:
            text = f"{text} (e-qaimə {ln.invoice})"
        rows.append(
            ActRow(
                [
                    i,
                    ru_date(ln.doc_date),
                    text,
                    ln.debit or None,
                    ln.credit or None,
                    ln.credit or None,  # mirrored: what we gave, they received
                    ln.debit or None,
                ]
            )
        )
    rows.append(
        ActRow(
            ["", "", trd("Обороты за период"), act.debit, act.credit, act.credit, act.debit],
            bold=True,
        )
    )
    rows.append(_balance_row(trd("Сальдо на конец"), act.closing))
    return rows


def _balance_row(caption: str, net: int) -> ActRow:
    debit, credit = (net, None) if net > 0 else (None, -net if net < 0 else None)
    return ActRow(["", "", caption, debit, credit, credit, debit], bold=True)


def _named(party: Party) -> str:
    return f"{party.title} (VÖEN {party.tax_id})" if party.tax_id else party.title


def _signature(party: Party) -> str:
    return trd("От имени {name}", name=party.title)


def _dmy(day: date) -> str:
    return day.strftime("%d.%m.%Y")
