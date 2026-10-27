# 2026-10-27 — claude/audit-window (D-new-main-window-composition)

Главное окно из цепочки наследования `CompanyFiles ← OpenPages ← ReportPlaces ← MainWindow`
(12 крючков `raise NotImplementedError`) — в композицию, тремя переносами без изменения логики:
`CompanySession` (QObject: файл компании; сигналы `opened`/`closing`/`none_left`, от страниц —
`confirm_close`, `notify`), `PageStack` (страницы, боковая панель, Esc; `place_wanted`,
`unpin_wanted`), `Navigator` + `ReportPlaces` (что где открывается); меню компании — `menus.py`.
`MainWindow(QMainWindow)` держит их полями, связывает в `_connect()`; методы, которые зовут
тесты и Ctrl+K, — делегаты. Классы: 485/315/245/429 строк → CompanySession 429, PageStack 273,
Navigator 371, ReportPlaces 215, MainWindow 338; крючков 12 → 0. Тесты: пять обращений к
приватному окна → части (ожидания те же), `screenshots.py` — `win.company.confirm_close`.
Попутно: «Показать файл» — `QProcess.startDetached` по пути из `shutil.which` (S603/S607),
лямбды PLW0108 → методы, `colorSchemeChanged` — к методу окна.
Хрупкое: порядок строк «Требует внимания» — порядок импорта модулей (`__init__` пакета грузит
`navigator` раньше `window`, чтобы порядок не поменялся); пример в `CODE_QUALITY.md` §3 ещё
называет старую цепочку окна (общий документ — не правил).
