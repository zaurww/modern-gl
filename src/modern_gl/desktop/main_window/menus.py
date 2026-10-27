"""The company menu (the company's name at the top of the sidebar): the companies, the
open company's file, the user's name, the language and the look."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu

from modern_gl.desktop import theme
from modern_gl.desktop.reports_page.table import grid, set_grid, set_zebra, zebra
from modern_gl.i18n import LANGUAGES, document_language, language, tr

if TYPE_CHECKING:
    from modern_gl.desktop.main_window.window import MainWindow


def mark(on: bool) -> str:
    return "✓  " if on else "    "


def company_menu(win: MainWindow) -> None:
    company = win.company
    menu = QMenu(win)
    viewing = company.session is not None and company.session.read_only
    for known in company.workspace.companies():
        current = known.path == company.company_path and not viewing
        act = menu.addAction(mark(current) + known.name)
        act.triggered.connect(lambda _=False, p=known.path: company.open_company(p))
    menu.addSeparator()
    menu.addAction(tr("Новая компания…")).triggered.connect(win.new_company)
    menu.addAction(tr("Добавить из файла…")).triggered.connect(company.add_company_file)
    menu.addAction(tr("Открыть для просмотра…")).triggered.connect(company.ask_view_company)
    if company.session is not None:
        menu.addSeparator()
        if viewing:
            menu.addAction(tr("Перечитать файл")).triggered.connect(company.reread)
        menu.addAction(tr("Показать файл компании")).triggered.connect(company.show_company_file)
        menu.addAction(tr("Передача дел…")).triggered.connect(company.hand_over)
        menu.addAction(tr("Журнал действий")).triggered.connect(
            lambda: win.reports.open_catalog_report("action_log")
        )
        if not company.session.stock_only:
            menu.addAction(tr("Проверка книги…")).triggered.connect(win.verify_books)
        if not viewing and not company.session.stock_only:
            menu.addAction(tr("Закрытие периода…")).triggered.connect(win.close_period)
        if not viewing:
            _file_actions(win, menu)
    menu.addSeparator()
    menu.addAction(tr("Ваше имя: {name}…", name=company.user_name())).triggered.connect(
        win.ask_user_name
    )
    languages = menu.addMenu(tr("Язык интерфейса"))
    for code, title in LANGUAGES.items():
        act = languages.addAction(mark(code == language()) + title)
        act.triggered.connect(lambda _=False, c=code: win.set_ui_language(c))
    _looks(win, menu.addMenu(tr("Оформление")))
    btn = win.sidebar.company
    menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))


def _file_actions(win: MainWindow, menu: QMenu) -> None:
    """What changes the open company's file (not shown while viewing)."""
    company = win.company
    s = company.open_session
    menu.addAction(tr("Сохранить как…")).triggered.connect(company.save_as)
    menu.addAction(tr("Сохранить копию…")).triggered.connect(company.save_copy)
    menu.addAction(tr("Резервные копии…")).triggered.connect(win.nav.show_backups)
    menu.addAction(tr("Восстановить из копии…")).triggered.connect(company.restore_company)
    menu.addAction(tr("Удалить компанию…")).triggered.connect(company.delete_company)
    menu.addSeparator()
    menu.addAction(tr("VÖEN компании…")).triggered.connect(company.edit_tax_id)
    menu.addAction(tr("Плательщик ƏDV с…")).triggered.connect(win.nav.edit_vat_payer)
    written = menu.addMenu(tr("Язык документов"))  # D152: the texts the program writes
    for code, title in LANGUAGES.items():
        act = written.addAction(mark(code == document_language()) + title)
        act.triggered.connect(lambda _=False, c=code: company.set_document_language(c))
    stock_only = menu.addAction(tr("Только склад (без бухгалтерии)"))
    stock_only.setCheckable(True)
    stock_only.setChecked(s.stock_only)
    stock_only.toggled.connect(company.set_stock_only)
    if not s.stock_only:
        books = menu.addAction(tr("Параллельные книги (МСФО, налог)"))
        books.setCheckable(True)
        books.setChecked(s.parallel_books)
        books.toggled.connect(company.set_parallel_books)


def _looks(win: MainWindow, looks: QMenu) -> None:
    """«Оформление»: the theme (or as the system), stripes and the grid of the reports."""
    system = theme.SYSTEM_THEME
    looks.addAction(
        mark(theme.current_theme() == system) + tr(theme.SYSTEM_TITLE)
    ).triggered.connect(lambda: win.set_ui_theme(system))
    looks.addSeparator()
    for name, (title, _) in theme.THEMES.items():
        act = looks.addAction(mark(name == theme.current_theme()) + tr(title))
        act.triggered.connect(lambda _=False, n=name: win.set_ui_theme(n))
    looks.addSeparator()
    stripes = looks.addAction(mark(zebra()) + tr("Полосы в таблицах"))
    stripes.triggered.connect(lambda: win.set_table_look(set_zebra, not zebra()))
    lines = looks.addAction(mark(grid()) + tr("Сетка в отчётах"))
    lines.triggered.connect(lambda: win.set_table_look(set_grid, not grid()))
