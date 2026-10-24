"""«Загрузить с портала» on the ƏDV deposit account (D112): a period chosen as in the
e-qaimə window (a day, a week, a month or any dates), what was loaded before shown and a
period loaded already not loaded again unasked (D115); signed in to the portal for this
company already — at once, else its page (D113); the operations read off the window's
thread, then shown with what each becomes before anything is written, and what became of
them after — in the window, each opening its document."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.deposit_import import (
    DepositFetched,
    loaded_already,
    loaded_spans,
    next_to_load,
    portal_loads,
    unfinished_days,
)
from modern_gl.application.bank.statement import place_balance
from modern_gl.application.ledger.bank_deposit import DRAFT, POSTED, DepositImported
from modern_gl.desktop.bank_page.deposit_fetch import DepositFetch, reconciled_changes
from modern_gl.desktop.bank_page.deposit_rows import DepositRows
from modern_gl.desktop.period_field import portal_period
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.dates import date_range
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

TITLE = "ƏDV depozit с портала"
PERIOD, PREVIEW, DONE = "period", "preview", "done"  # the window's steps


class DepositDialog(QDialog):
    """Period → sign in → the portal's operations of the period, what each becomes →
    «Провести» (or «Создать черновики») → what became of them; `imported` — what the
    import did, `chosen_document` — the document double-clicked to open."""

    def __init__(
        self,
        session: Session,
        place: BankPlace,
        parent: QWidget | None = None,
        sign_in: Callable[..., str | None] | None = None,
        today: date | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.place = place
        self.today = today or date.today()
        self.fetch = DepositFetch(self, session, sign_in, self.today)
        self.fetch.progress.connect(lambda text: self.status.setText(text))
        self.fetch.loaded.connect(self._loaded)
        self.fetch.failed.connect(self._failed)
        self.fetched: DepositFetched | None = None
        self.imported: DepositImported | None = None
        self.chosen_document: int | None = None
        self.step = PERIOD
        self.loads = portal_loads(session.conn, session.company_id, place)
        self.setWindowTitle(tr(TITLE))
        self.resize(860, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        title = QLabel(tr(TITLE))
        title.setFont(fonts().title)
        root.addWidget(title)
        account = QLabel(place.name)
        account.setObjectName("secondary")
        root.addWidget(account)
        self.period_field = portal_period(self.today)
        self.period_field.changed.connect(self._period_changed)
        root.addWidget(self.period_field)
        self.loaded = QLabel()
        self.loaded.setWordWrap(True)
        root.addWidget(self.loaded)
        self.changes = QLabel()  # a reconciled period changed since (D118)
        self.changes.setObjectName("warning")
        self.changes.setWordWrap(True)
        root.addWidget(self.changes)
        self._build_rows(root)
        self._build_actions(root)
        self._suggest_period()
        self._show_loaded()
        self._show_changes()
        self._show_step(PERIOD)

    def _build_rows(self, root: QVBoxLayout) -> None:
        self.status = QLabel(
            tr(
                "Выберите период и нажмите «Загрузить с портала»: если вход на портал не "
                "открыт, откроется его страница (ASAN İmza)."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.rows = DepositRows()
        self.rows.itemChanged.connect(lambda *_: self._show_balances())
        self.rows.document_chosen.connect(self._open_document)
        root.addWidget(self.rows, 1)
        self.balances = QLabel()
        self.balances.setWordWrap(True)
        root.addWidget(self.balances)
        self.spacer = QWidget()  # the air under the period while there are no rows
        root.addWidget(self.spacer, 1)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.close_button = button(tr("Закрыть"), "flat")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        self.drafts_button = button(tr("Создать черновики"), "flat")
        self.drafts_button.clicked.connect(lambda: self.write(post=False))
        actions.addWidget(self.drafts_button)
        self.post_button = button(tr("Провести"), "primary")
        self.post_button.clicked.connect(lambda: self.write(post=True))
        actions.addWidget(self.post_button)
        self.load_button = button(tr("Загрузить с портала"), "primary")
        self.load_button.clicked.connect(self.load)
        actions.addWidget(self.load_button)
        root.addLayout(actions)

    def _show_step(self, step: str) -> None:
        """One blue button at a time (D86): load, then post, then nothing — «Готово»."""
        self.step = step
        self.load_button.setVisible(step == PERIOD)
        self.post_button.setVisible(step == PREVIEW)
        self.drafts_button.setVisible(step == PREVIEW)
        self.rows.setVisible(step != PERIOD)
        self.balances.setVisible(step != PERIOD)
        self.spacer.setVisible(step == PERIOD)
        self.period_field.setEnabled(step != DONE)
        self.close_button.setText(tr("Готово") if step == DONE else tr("Закрыть"))
        if step != PERIOD:
            self.resize(max(self.width(), 1040), max(self.height(), 560))

    def _suggest_period(self) -> None:
        """From the day after the last one loaded (a day loaded before it ended — from it)
        up to today; nothing loaded yet — this month."""
        start = next_to_load(self.loads)
        if start is None:
            return
        following = date.fromisoformat(start)
        if following <= self.today:
            self.period_field.set_period(following, self.today)

    def period(self) -> tuple[date, date]:
        """The period chosen, up to today: the portal has no operations of tomorrow."""
        return self.period_field.period()

    def _period_changed(self) -> None:
        self._show_loaded()
        if self.step == PREVIEW:  # the rows were of another period
            self.fetched = None
            self.status.setText(tr("Период изменён — загрузите его с портала."))
            self._show_changes()
            self._show_step(PERIOD)

    def _show_loaded(self) -> None:
        spans = loaded_spans(self.loads)
        if not self.loads:
            self.loaded.setObjectName("secondary")
            self.loaded.setText(tr("С портала в этот счёт ещё ничего не загружалось."))
        else:
            text = " ".join(self._loaded_texts(spans))
            first, last = self.period()
            again = self.step != DONE and loaded_already(
                self.loads, first.isoformat(), last.isoformat()
            )
            if again:
                text += " " + tr("Выбранный период уже загружен.")
            self.loaded.setObjectName("warning" if again else "secondary")
            self.loaded.setText(text)
        self.loaded.style().unpolish(self.loaded)
        self.loaded.style().polish(self.loaded)

    def _show_changes(self) -> None:
        """A reconciled period that changed since — in the books at once, on the portal
        once it is read: said here too, not only in the reconciliation window."""
        changes = reconciled_changes(self.s, self.place, self.fetched)
        self.changes.setText(" ".join(f"{text}." for text in changes))
        self.changes.setVisible(bool(changes))

    def _loaded_texts(self, spans: list[tuple[str, str]]) -> list[str]:
        texts = []
        if spans:
            periods = (date_range(a, b, "–") for a, b in spans)
            texts.append(tr("Уже загружено с портала: {periods}.", periods=", ".join(periods)))
        unfinished = [
            date.fromisoformat(d).strftime("%d.%m.%Y") for d in unfinished_days(self.loads)
        ]
        if unfinished:
            texts.append(
                tr(
                    "{days} загружено, пока день не кончился: поздние операции этого дня "
                    "возьмутся при следующей загрузке.",
                    days=", ".join(unfinished),
                )
            )
        return texts

    # ---- loading -------------------------------------------------------------------

    def load(self) -> None:
        first, last = self.period()
        if last < first:
            self.status.setText(tr("начало периода позже конца"))
            return
        if loaded_already(self.loads, first.isoformat(), last.isoformat()) and not self._again(
            first, last
        ):
            return
        self.load_button.setEnabled(False)
        if self.fetch.start(first, last):
            self.status.setText(tr("Загрузка с портала…"))
        else:
            self.load_button.setEnabled(True)

    def _again(self, first: date, last: date) -> bool:
        question = tr(
            "Период {period} уже загружен с портала. Загрузить снова?\n\nДвойных операций "
            "не будет: добавятся только новые, появившиеся на портале после прошлой загрузки.",
            period=date_range(first, last, "–"),
        )
        answer = QMessageBox.question(self, tr(TITLE), question)
        return answer == QMessageBox.StandardButton.Yes

    def _failed(self, message: str) -> None:
        self.load_button.setEnabled(True)
        self.status.setText(message)

    def _loaded(self, fetched: DepositFetched) -> None:
        """What the import would do, shown; nothing written yet."""
        self.load_button.setEnabled(True)
        try:
            seen = self.s.ledger.bank.preview_vat_deposit(
                self.s.company_id,
                self.place,
                fetched.operations,
                fetched.balance,
                (fetched.date_from, fetched.date_to),
            )
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.fetched = fetched
        self.rows.blockSignals(True)
        self.rows.show_rows(seen.rows, written=False)
        self.rows.blockSignals(False)
        self.status.setText(preview_summary(seen))
        self._show_changes()
        self._show_step(PREVIEW)
        self._show_balances()

    def write(self, post: bool) -> None:
        """The operations ticked into the books: posted, or all of them drafts."""
        fetched = self.fetched
        if fetched is None:
            return
        try:
            done = self.s.ledger.bank.import_vat_deposit(
                self.s.company_id,
                self.place,
                fetched.operations,
                fetched.balance,
                (fetched.date_from, fetched.date_to),
                take=self.rows.taken(),
                post=post,
            )
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.imported = done
        self.loads = portal_loads(self.s.conn, self.s.company_id, self.place)
        self.step = DONE
        self._show_loaded()
        self.rows.show_rows(done.rows, written=True)
        text = summary(done)
        if any(row.document_id is not None for row in done.rows):
            text += ". " + tr("Двойной щелчок по строке — открыть документ.")
        self.status.setText(text)
        self._show_changes()  # what was written may change a reconciled period
        self._show_step(DONE)
        self._show_balances()

    def _show_balances(self) -> None:
        """The portal's balance now beside the books' — and, before writing, the books'
        after the operations ticked are posted."""
        if self.fetched is None:
            return
        books = place_balance(self.s.conn, self.s.company_id, self.place, self.today.isoformat())
        portal = self.fetched.balance
        text = tr(
            "На портале сейчас {portal} ₼, в программе {books} ₼",
            portal=format_minor(portal),
            books=format_minor(books),
        )
        after = books
        if self.step == PREVIEW:
            after += sum(r.op.net for r in self.rows.rows(ticked_only=True) if r.state == POSTED)
            text += tr(", после загрузки будет {after} ₼", after=format_minor(after))
        if after != portal:
            text += tr(" — разница {diff} ₼", diff=format_minor(portal - after))
        self.balances.setText(text + ".")
        self.balances.setObjectName("warning" if after != portal else "secondary")
        self.balances.style().unpolish(self.balances)
        self.balances.style().polish(self.balances)

    def _open_document(self, document_id: int) -> None:
        self.chosen_document = document_id
        self.accept()


def preview_summary(seen: DepositImported) -> str:
    """What the import is about to do, in one line over the rows."""
    posted = sum(1 for row in seen.rows if row.state == POSTED)
    drafts = sum(1 for row in seen.rows if row.state == DRAFT)
    if not (posted or drafts or seen.linked):
        return tr("Новых операций нет — запишутся только остатки дней по порталу.")
    text = tr(
        "Будет проведено {posted}, черновиками {drafts} (причина — в строке)",
        posted=posted,
        drafts=drafts,
    )
    if seen.linked:
        text += tr(", введённых вручную будет связано {n}", n=seen.linked)
    if seen.known:
        text += tr(", уже есть {n}", n=seen.known)
    if seen.counterparties:
        text += tr(", новых контрагентов {n}", n=seen.counterparties)
    return text + ". " + tr("Снимите галочку с того, что загружать не нужно.")


def summary(done: DepositImported) -> str:
    """What the import did, in one line after it."""
    text = tr(
        "С портала: проведено {posted}, не разнесено {drafts}",
        posted=done.posted,
        drafts=len(done.drafts),
    )
    if done.counterparties:
        text += tr(", новых контрагентов {n}", n=done.counterparties)
    if not (done.posted or done.drafts or done.linked):
        text += tr(" — новых операций нет")
    return text
