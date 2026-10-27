"""«Проверка книги» (D175): the program asks its data whether they agree. Each check is a
row: a passed one is quiet (a check mark), one that found something lists it, and a
finding about a document opens it. What the program can put right itself — the modules'
postings — is the one blue button, not shown while viewing (D80)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.verification import (
    REBUILD,
    CheckResult,
    Finding,
    rebuild_modules,
    verify,
)
from modern_gl.desktop.icons import icon
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import button, caption, hide_when_viewing
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

SHOWN = 20  # findings shown under a check; the rest is a count


class VerificationDialog(QDialog):
    def __init__(self, session: Session, open_document: Callable[[int], None], parent=None) -> None:
        super().__init__(parent)
        self.s, self.open_document = session, open_document
        self.changed: list[int] = []  # GL documents a rebuild changed: the pages hear of them
        self.setWindowTitle(tr("Проверка книги"))
        self.setMinimumSize(560, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)
        self.title = QLabel()
        self.title.setFont(fonts().heading)
        root.addWidget(self.title)
        why = caption(
            tr(
                "Программа сверяет свои данные: файл, правила проведения, сторно, проводки "
                "модулей и склад. В файле ничего не меняется."
            )
        )
        why.setWordWrap(True)
        root.addWidget(why)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.list = self._new_list()
        root.addWidget(self.area, 1)
        root.addLayout(self._buttons())
        self.run()

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        close = button(tr("Закрыть"))
        close.clicked.connect(self.accept)
        self.rebuild = button(tr("Перестроить проводки"), "primary")
        self.rebuild.clicked.connect(lambda _=False: self.rebuild_postings())
        self.rebuild.hide()
        row.addWidget(close)
        row.addWidget(self.rebuild)
        return row

    def run(self) -> None:
        self.title.setText(tr("Проверяю…"))
        cid = self.s.company_id
        self.s.read(self, lambda conn: verify(conn, cid), self.show_results, self._failed)

    def show_results(self, results: list[CheckResult]) -> None:
        self.list = self._new_list()
        found = sum(len(r.findings) for r in results)
        self.title.setText(
            tr("Всё сходится") if not found else tr("Найдено расхождений: {n}", n=found)
        )
        for result in results:
            self._add(result)
        self.list.addStretch(1)
        repairable = any(r.repair == REBUILD and not r.ok for r in results)
        self.rebuild.setVisible(repairable)
        hide_when_viewing(self.s.read_only, self.rebuild)

    def _new_list(self) -> QVBoxLayout:
        """An empty list in the scroll area; the one shown before goes with its rows."""
        holder = QWidget()
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        self.area.setWidget(holder)
        return rows

    def _add(self, result: CheckResult) -> None:
        head = QHBoxLayout()
        mark = QLabel()
        name = "check" if result.ok else "attention"
        mark.setPixmap(icon(name, P.muted if result.ok else P.amber).pixmap(16, 16))
        head.addWidget(mark)
        title = QLabel(result.title)
        if result.ok:
            title.setObjectName("secondary")
        else:
            title.setFont(fonts().bold)
        head.addWidget(title, 1)
        self.list.addLayout(head)
        for finding in result.findings[:SHOWN]:
            self.list.addWidget(self._finding(finding))
        if len(result.findings) > SHOWN:
            more = caption(tr("и ещё {n}", n=len(result.findings) - SHOWN))
            more.setContentsMargins(26, 0, 0, 0)
            self.list.addWidget(more)

    def _finding(self, finding: Finding) -> QWidget:
        if finding.document_id is None:
            label = QLabel(finding.text)
            label.setWordWrap(True)
            label.setContentsMargins(26, 0, 0, 0)
            return label
        link = button(finding.text, "crumb", tr("Открыть документ"))
        doc_id = finding.document_id
        link.clicked.connect(lambda _=False: self._open(doc_id))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(26, 0, 0, 0)
        line.addWidget(link)
        line.addStretch(1)
        return row

    def _open(self, doc_id: int) -> None:
        self.accept()
        self.open_document(doc_id)

    def rebuild_postings(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("Перестроить проводки"),
            tr(
                "Проводки банка, конвертации и склада открытого периода будут построены "
                "заново по их документам. Прежние останутся в истории изменений."
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            changed = rebuild_modules(self.s.ledger, self.s.company_id)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Перестроить проводки"), str(e))
            return
        self.changed += changed
        self.s.notify(tr("Перестроено документов: {n}", n=len(changed)))
        self.run()

    def _failed(self, error: LedgerError) -> None:
        self.title.setText(tr("Проверка не закончена"))
        self.list = self._new_list()
        self.list.addWidget(QLabel(str(error)))
