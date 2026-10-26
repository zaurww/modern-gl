"""«Загрузить выписку из файла» (D146): the bank's statement files read, each matched to
a bank account by its IBAN (an account not known — chosen once, it keeps the IBAN), then
shown with what each line becomes before anything is written: the lines to check first,
with why; «Провести» (or «Создать черновики») writes the lines ticked, the window shows
what became of them, a double click opens a document."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.file_commands import FileImported
from modern_gl.application.bank.file_import import FileOperation, account_choices, iban_places
from modern_gl.application.bank.files import BankFile, read_bank_file
from modern_gl.application.bank.imported import DRAFT, KNOWN, POSTED, ImportRow
from modern_gl.application.bank.statement import place_balance
from modern_gl.desktop.bank_page.import_rows import ImportRows
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.dates import date_range
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

TITLE = "Выписка из файла"


class BankFileDialog(QDialog):
    """Files → accounts → the lines, what each becomes → «Провести» → what became of
    them; `imported` — what the import did, `chosen_document` — the one to open."""

    def __init__(
        self,
        session: Session,
        paths: Sequence[str | Path],
        place: BankPlace | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.imported: FileImported | None = None
        self.chosen_document: int | None = None
        self.files: list[BankFile] = []
        errors = []
        for path in paths:
            try:
                self.files.append(read_bank_file(path))
            except LedgerError as e:
                errors.append(str(e))
        self.setWindowTitle(tr(TITLE))
        self.resize(1080, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        title = QLabel(tr(TITLE))
        title.setFont(fonts().title)
        root.addWidget(title)
        self.accounts: dict[str, QComboBox] = {}
        self._build_files(root, place)
        self.errors = QLabel("\n".join(errors))
        self.errors.setObjectName("warning")
        self.errors.setWordWrap(True)
        self.errors.setVisible(bool(errors))
        root.addWidget(self.errors)
        self.status = QLabel()
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.rows = ImportRows()
        self.rows.itemChanged.connect(lambda *_: self._show_balances())
        self.rows.document_chosen.connect(self._open_document)
        root.addWidget(self.rows, 1)
        self.balances = QLabel()
        self.balances.setWordWrap(True)
        root.addWidget(self.balances)
        self._build_actions(root)
        self.preview()

    def _build_files(self, root: QVBoxLayout, place: BankPlace | None) -> None:
        """A row per file: what it is, and the account it goes to."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        known = iban_places(self.s.conn, self.s.company_id)
        for n, file in enumerate(self.files):
            text = " · ".join(
                (file.bank, file.iban, file.currency, date_range(file.date_from, file.date_to, "–"))
            )
            about = QLabel(f"{file.file_name}\n{text}")
            about.setObjectName("secondary")
            grid.addWidget(about, n, 0)
            box = QComboBox()
            box.addItem(tr("— выберите счёт —"), None)
            choices = account_choices(self.s.conn, self.s.company_id, file.currency)
            for choice in choices:
                box.addItem(f"{choice.account_code}  {choice.name}", choice)
            fits = known.get(file.iban)
            if fits is None and place is not None and place in choices:
                fits = place  # opened from that account: the file is likely its
            if fits is not None and fits in choices:
                box.setCurrentIndex(choices.index(fits) + 1)
            box.currentIndexChanged.connect(lambda *_: self.preview())
            grid.addWidget(box, n, 1)
            self.accounts[file.iban] = box
        grid.setColumnStretch(0, 1)
        root.addLayout(grid)

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
        root.addLayout(actions)

    def places(self) -> dict[str, BankPlace]:
        """IBAN -> the account chosen for its file."""
        chosen = {}
        for iban, box in self.accounts.items():
            place = box.currentData()
            if place is not None:
                chosen[iban] = place
        return chosen

    def preview(self) -> None:
        """What the import would do, nothing written: the lines to check first."""
        places = self.places()
        waiting = [f.file_name for f in self.files if f.iban not in places]
        try:
            seen = self.s.ledger.bank.preview_bank_files(self.s.company_id, self.files, places)
        except LedgerError as e:
            self._show_rows([], text=str(e))
            return
        text = preview_summary(seen)
        if waiting:
            text = tr("Выберите счёт для: {files}.", files=", ".join(waiting)) + " " + text
        self._show_rows(drafts_first(seen.rows), text)

    def _show_rows(self, rows: list[ImportRow], text: str) -> None:
        self.rows.blockSignals(True)
        self.rows.show_rows(rows, written=False)
        self.rows.blockSignals(False)
        self.status.setText(text)
        can = any(row.state != KNOWN for row in rows)
        self.post_button.setEnabled(can)
        self.drafts_button.setEnabled(can)
        self._show_balances()

    def write(self, post: bool) -> None:
        """The lines ticked into the books: posted when sure, or all of them drafts."""
        try:
            done = self.s.ledger.bank.import_bank_files(
                self.s.company_id, self.files, self.places(), take=self.rows.taken(), post=post
            )
        except LedgerError as e:
            self.status.setText(str(e))
            return
        self.imported = done
        self.rows.show_rows(drafts_first(done.rows), written=True)
        text = summary(done)
        if any(row.document_id is not None for row in done.rows):
            text += ". " + tr("Двойной щелчок по строке — открыть документ.")
        self.status.setText(text)
        for box in self.accounts.values():
            box.setEnabled(False)
        self.post_button.setVisible(False)
        self.drafts_button.setVisible(False)
        self.close_button.setText(tr("Готово"))
        self._show_balances()

    def _show_balances(self) -> None:
        """Each account: the bank's balance at the file's end beside the books' — before
        writing, as they will be once the lines ticked are posted. A difference the drafts
        to check make is no alarm: it goes once they are posted."""
        places = self.places()
        texts, differs = [], False
        ticked = self.rows.rows(ticked_only=True)

        def net(state: str, place: BankPlace) -> int:
            return sum(
                r.op.net
                for r in ticked
                if r.state == state and isinstance(r.op, FileOperation) and r.op.place == place
            )

        for file in self.files:
            place = places.get(file.iban)
            if place is None:
                continue
            books = place_balance(self.s.conn, self.s.company_id, place, file.date_to)
            if self.imported is None:
                books += net(POSTED, place)
            text = tr(
                "{account}: по выписке {bank} {currency}, в программе {books}",
                account=place.name,
                bank=format_minor(file.closing),
                currency=file.currency,
                books=format_minor(books),
            )
            drafts = net(DRAFT, place)
            if books + drafts != file.closing:
                differs = True
                text += tr(" — разница {diff}", diff=format_minor(file.closing - books))
            elif drafts:
                text += tr(
                    " — сойдётся, когда будут проведены черновики ({drafts})",
                    drafts=format_minor(drafts),
                )
            texts.append(text)
        self.balances.setText(".\n".join(texts) + ("." if texts else ""))
        self.balances.setObjectName("warning" if differs else "secondary")
        self.balances.style().unpolish(self.balances)
        self.balances.style().polish(self.balances)

    def _open_document(self, document_id: int) -> None:
        self.chosen_document = document_id
        self.accept()


def drafts_first(rows: list[ImportRow]) -> list[ImportRow]:
    """The lines to check above, the rest in the order of the files."""
    return sorted(rows, key=lambda row: row.state != DRAFT)


def preview_summary(seen: FileImported) -> str:
    if not (seen.posted or seen.drafts):
        return tr("Новых строк нет — запишутся только остатки дней по выписке.")
    text = tr(
        "Будет проведено {posted}, на проверку черновиками {drafts} (причина — в строке)",
        posted=seen.posted,
        drafts=seen.drafts,
    )
    if seen.known:
        text += tr(", уже есть {n}", n=seen.known)
    if seen.counterparties:
        text += tr(", новых контрагентов {n}", n=seen.counterparties)
    return text + ". " + tr("Снимите галочку с того, что загружать не нужно.")


def summary(done: FileImported) -> str:
    text = tr(
        "Из выписки: проведено {posted}, на проверку {drafts}",
        posted=done.posted,
        drafts=done.drafts,
    )
    if done.counterparties:
        text += tr(", новых контрагентов {n}", n=done.counterparties)
    if not (done.posted or done.drafts):
        text += tr(" — новых строк нет")
    return text
