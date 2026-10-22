"""Reports on one account: its card, its subconto balances and its analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
)

from modern_gl.desktop.reports_page.view import (
    Column,
    ReportPage,
    ReportParams,
    turnover_columns,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    balance_text,
    money,
    ru_date,
)
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.i18n import tr
from modern_gl.reporting import reports
from modern_gl.reporting.reports import SubcontoRow, Turnovers


class AccountReportPage(ReportPage):
    kind = ""
    caption = ""

    def __init__(self, session: Session, account_id: int, params: ReportParams) -> None:
        self.account_id = account_id
        acc = session.catalog.accounts[account_id]
        super().__init__(session, f"{tr(self.caption)} {acc.short}", params)
        self.header.title.setText(self.title())
        self.header.subtitle.setText(acc.name)
        self.key = (self.kind, account_id, *self.params.subconto)
        self.add_filters()
        self.refresh()

    def add_filters(self) -> None:
        """Choices of the report itself, before «Сформировать» (none by default)."""

    @property
    def account(self):
        return self.s.catalog.accounts[self.account_id]

    def title(self) -> str:
        names = self._subconto_names()
        return f"{tr(self.caption)} {self.account.short}" + (f" · {names[-1]}" if names else "")

    def _subconto_names(self) -> list[str]:
        """The counterparty (and contract) the report is about, if it is about one."""
        return [
            self.s.catalog.value(v).name if v is not None else tr("<не указано>")
            for v in self.params.subconto
        ]

    def refresh(self) -> None:
        super().refresh()
        acc = self.account
        name = acc.name if acc.code else ""  # without a code the name is the title already
        parts = (
            name,
            " · ".join(self._subconto_names()),
            self.params.describe(self.s.parallel_books),
        )
        self.header.subtitle.setText("   ·   ".join(part for part in parts if part))


def invoice_text(line: reports.CardLine) -> str:
    """An e-qaimə number; a customs declaration is marked as such."""
    if line.invoice_kind == CUSTOMS:
        return f"{tr('bəyannamə')} {line.invoice}"
    return line.invoice


@dataclass
class CardEdge:
    """The first and last rows of a card: the balances, and the turnovers at the end."""

    memo: str
    balance: int
    debit: int | None = None
    credit: int | None = None
    doc_date: str = ""
    number: int = 0
    document_id: int = 0
    corr_code: str = ""
    currency: str = ""
    currency_debit: int | None = None
    currency_credit: int | None = None
    invoice: str = ""
    invoice_kind: str = ""


class CardPage(AccountReportPage):
    kind, caption = "card", "Карточка счёта"

    def build(self) -> None:
        card = reports.account_card(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
            self.params.subconto,
        )
        # within one year the year is in the period already
        one_year = self.params.date_from.year == self.params.date_to.year
        columns = [
            Column(tr("Дата"), lambda ln: self._date(ln.doc_date, one_year), width=1),
            Column("№", lambda ln: ln.number or "", width=1),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Корр. счёт"), lambda ln: ln.corr_code, width=1),
            Column(tr("Дт"), lambda ln: ln.debit, money=True, group=tr("Обороты")),
            Column(tr("Кт"), lambda ln: ln.credit, money=True, group=tr("Обороты")),
            Column(
                tr("Сальдо"),
                lambda ln: balance_text(ln.balance) if ln.balance else "",
                right=True,
            ),
        ]
        if card.currency_closing or self.account.currency:
            columns[4:4] = [
                Column(tr("Валюта"), lambda ln: ln.currency, width=1),
                Column(tr("Дт"), lambda ln: ln.currency_debit, money=True, group=tr("В валюте")),
                Column(tr("Кт"), lambda ln: ln.currency_credit, money=True, group=tr("В валюте")),
            ]
        if any(ln.invoice for ln in card.lines):
            columns.insert(3, Column(tr("E-qaimə"), invoice_text, width=1))
        opening = CardEdge(tr("Сальдо на начало"), card.opening)
        closing = CardEdge(
            tr("Обороты и сальдо на конец"),
            card.closing,
            sum(ln.debit for ln in card.lines),
            sum(ln.credit for ln in card.lines),
        )
        self.model.set(
            columns,
            [opening, *card.lines, closing] if card.lines else [],
            emphasis=lambda ln: ln is closing,
            muted=lambda ln: ln is opening,
            total=lambda ln: ln is closing,
        )
        text = tr(
            "Сальдо на начало: {start}      Сальдо на конец: {end}",
            start=balance_text(card.opening),
            end=balance_text(card.closing),
        )
        in_currency = [
            f"{code} {balance_text(net)}" for code, net in sorted(card.currency_closing.items())
        ]
        if in_currency:
            text += "      " + tr("В валюте на конец: {amounts}", amounts=",  ".join(in_currency))
        self.footer.setText(text)

    @staticmethod
    def _date(iso: str, one_year: bool) -> str:
        text = ru_date(iso) if iso else ""
        return text[:5] if one_year else text

    def drill(self, row) -> None:
        if row is not None and row.document_id:
            self.open_document.emit(row.document_id)


class SubcontoPage(AccountReportPage):
    kind, caption = "subconto", "ОСВ по субконто"

    def add_filters(self) -> None:
        """«Метка»: only the elements with it — the related parties, the landlords (D64).
        Shown when some element of the directory has a tag. «Детализация»: counterparties,
        or counterparties and their contracts under them — when the account has both."""
        self.tag = QComboBox()
        self.tag.setMinimumWidth(190)
        self.tag_label = QLabel(tr("Метка"))
        self.tag_label.setObjectName("secondary")
        self.levels = QComboBox()
        self.levels.setMinimumWidth(190)
        kinds = self._kinds()
        for n in range(1, len(kinds) + 1):
            self.levels.addItem(" → ".join(kinds[:n]))
        self.levels.setCurrentIndex(len(kinds) - 1)  # down to the contracts, as asked for
        levels_label = QLabel(tr("Детализация"))
        levels_label.setObjectName("secondary")
        at = self.bar.count() - 2  # before «Сформировать»
        for w in (levels_label, self.levels, self.tag_label, self.tag):
            self.bar.insertWidget(at, w)
            at += 1
            if w in (self.levels, self.tag):
                self.bar.insertSpacing(at, 6)
                at += 1
        for w in (levels_label, self.levels):
            w.setVisible(len(kinds) > 1)
        self._fill_tags()
        self.tag.activated.connect(lambda _: self.refresh())
        self.levels.activated.connect(lambda _: self.refresh())

    def _kinds(self) -> list[str]:
        """The names of the account's subconto in a row: Контрагенты, Договоры."""
        kinds = []
        for kind_id in self.account.sc_kinds:
            if kind_id is None:
                break
            kinds.append(self.s.catalog.kinds[kind_id])
        return kinds

    def _fill_tags(self) -> None:
        kind_id = self.account.sc_kinds[0]
        tags = self.s.catalog.kind_tags(kind_id) if kind_id is not None else []
        current = self.tag.currentData()
        self.tag.blockSignals(True)
        self.tag.clear()
        self.tag.addItem(tr("Все"), None)
        for tag_id, name in tags:
            self.tag.addItem(name, tag_id)
        self.tag.setCurrentIndex(max(self.tag.findData(current), 0))
        self.tag.blockSignals(False)
        for w in (self.tag, self.tag_label):
            w.setVisible(bool(tags))

    def build(self) -> None:
        self._fill_tags()  # a tag given in «Справочники» since the report was opened
        tag_id = self.tag.currentData()
        levels = self.levels.currentIndex() + 1
        rows = reports.subconto_balance(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
            tag_id=tag_id,
            levels=levels,
        )
        total = SubcontoRow(name=tr("Итого"))
        for r in rows:
            if r.depth == 0:  # a contract is in its counterparty already
                total.add(
                    Turnovers(
                        r.opening_dt,
                        r.opening_ct,
                        r.turnover_dt,
                        r.turnover_ct,
                        r.closing_dt,
                        r.closing_ct,
                    )
                )
        columns = [
            Column(" / ".join(self._kinds()[:levels]), lambda r: "      " * r.depth + r.name)
        ]
        if any(self._tax_id(r) for r in rows):  # counterparties with a VÖEN
            columns.append(Column(tr("VÖEN"), self._tax_id, width=130))
        columns += turnover_columns()
        if any(r.currency_closing for r in rows):  # a foreign partner: USD and EUR apart
            columns.append(Column(tr("В валюте на конец"), self._in_currency, width=200))
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total or (levels > 1 and r.depth == 0),
            muted=lambda r: r.depth > 0,
            total=lambda r: r is total,
        )
        self.footer.setText(
            tr("Только с меткой «{name}»", name=self.tag.currentText()) if tag_id else ""
        )

    def drill(self, row) -> None:
        """The card of this counterparty (or contract) — and from it the documents."""
        if row is not None and row.path:
            self.open_report.emit("card", self.account_id, replace(self.params, subconto=row.path))

    @staticmethod
    def _in_currency(row: SubcontoRow) -> str:
        return ",  ".join(
            f"{code} {balance_text(net)}" for code, net in sorted(row.currency_closing.items())
        )

    def _tax_id(self, row: SubcontoRow) -> str:
        if row.value_id is None:
            return ""
        return self.s.catalog.value(row.value_id).tax_id or ""


class AnalysisPage(AccountReportPage):
    kind, caption = "analysis", "Анализ счёта"

    def build(self) -> None:
        rows = reports.account_analysis(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        columns = [
            Column(tr("Корр. счёт"), lambda r: r.corr_code, width=1),
            Column(tr("Наименование"), lambda r: r.corr_name),
            Column(tr("Дт"), lambda r: r.debit, money=True, group=tr("Обороты")),
            Column(tr("Кт"), lambda r: r.credit, money=True, group=tr("Обороты")),
        ]
        dt, ct = sum(r.debit for r in rows), sum(r.credit for r in rows)
        total = reports.CorrRow("", tr("Итого"), dt, ct)
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total,
            total=lambda r: r is total,
        )
        self.footer.setText(
            tr("Оборот Дт: {dt}      Оборот Кт: {ct}", dt=money(dt, False), ct=money(ct, False))
        )

    def drill(self, row) -> None:
        if row is not None and row.corr_id in self.s.catalog.accounts:
            self.open_report.emit("card", row.corr_id, self.params)


REPORTS: dict[str, type[AccountReportPage]] = {
    "card": CardPage,
    "subconto": SubcontoPage,
    "analysis": AnalysisPage,
}
