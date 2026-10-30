"""Saved views of the trial balance (D190): «⋯ → Вид „…“» puts the
page as it was — how deep, the splits under the accounts, the order, one column, the
precision; «Сохранить вид…» keeps the page as it is now under a name, in the company's
file (it names this company's accounts and directory elements)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QInputDialog

from modern_gl.application import queries
from modern_gl.desktop.widgets import MenuItem
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

if TYPE_CHECKING:
    from modern_gl.desktop.reports_page.osv import OsvPage

REPORT = "osv"


class OsvViews:
    def __init__(self, page: OsvPage) -> None:
        self.page = page
        self.current: str | None = None  # the name of the view the page shows

    # ---- what a view holds -------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        page = self.page
        if page.top_only.isChecked():
            detail = "top"
        else:
            detail = "subconto" if page.expand.isChecked() else "sub"
        return {
            "detail": detail,
            "currency": page.in_currency.isChecked(),
            "sections": page.sections.isChecked(),
            "net": page.net,
            "scale": page.model.scale,
            "sort": list(page.sort) if page.sort else None,
            "opened": page.tree.to_list(),
        }

    def apply(self, name: str, settings: dict[str, Any]) -> None:
        """The page as the view says; what it does not say stays as it is."""
        page = self.page
        buttons = {"top": page.top_only, "subconto": page.expand, "sub": page.sub}
        buttons.get(str(settings.get("detail")), page.sub).setChecked(True)
        page.in_currency.setChecked(bool(settings.get("currency", False)))
        page.sections.setChecked(bool(settings.get("sections", False)))
        page.net = bool(settings.get("net", False))
        scale = settings.get("scale", 1)
        page.model.scale = scale if isinstance(scale, int) and scale > 0 else 1
        sort = settings.get("sort")
        page.sort = (
            (str(sort[0]), bool(sort[1])) if isinstance(sort, list) and len(sort) == 2 else None
        )
        page.tree.from_list(settings.get("opened") or [])
        self.current = name
        page.refresh()

    # ---- «⋯» ---------------------------------------------------------------------------

    def items(self) -> list[MenuItem]:
        views = queries.report_views(self.page.s.conn, self.page.s.company_id, REPORT)
        items: list[MenuItem] = [
            (
                ("✓  " if v.name == self.current else "    ") + tr("Вид «{name}»", name=v.name),
                lambda v=v: self.apply(v.name, v.settings),
            )
            for v in views
        ]
        if self.page.s.read_only:
            return items
        items.append((tr("Сохранить вид…"), self.save))
        if self.current is not None:
            items.append((tr("Удалить вид «{name}»", name=self.current), self.delete))
        return items

    def save(self) -> None:
        name, ok = QInputDialog.getText(
            self.page, tr("Сохранить вид"), tr("Название вида"), text=self.current or ""
        )
        if not ok or not name.strip():
            return
        try:
            self.page.s.ledger.save_report_view(
                self.page.s.company_id, REPORT, name, self.settings()
            )
        except LedgerError as e:
            self.page.s.notify(str(e))
            return
        self.current = name.strip()
        self.page.show_subtitle()
        self.page.s.notify(tr("Вид «{name}» сохранён", name=self.current))

    def delete(self) -> None:
        name = self.current
        if name is None:
            return
        views = queries.report_views(self.page.s.conn, self.page.s.company_id, REPORT)
        found = next((v for v in views if v.name == name), None)
        if found is not None:
            self.page.s.ledger.delete_report_view(self.page.s.company_id, found.id)
        self.current = None
        self.page.show_subtitle()
        self.page.s.notify(tr("Вид «{name}» удалён", name=name))
