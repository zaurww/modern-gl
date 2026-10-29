# 2026-10-27 — claude/audit-desktop (D1881, D1882, D1883)

Внедрение аудита слоя `desktop` и тестов UI (задание координатора; `application/` параллельно
правила другая сессия — не тронут, кроме чтения).

- **Протокол страницы** `desktop/page.py` (`Page`, `PageWidget`, `EmptyPage`): окно зовёт
  `activated()` / `on_postings_changed()` у страниц; isinstance-цепочки и `getattr` убраны.
- **Реестр клавиш** `desktop/shortcuts.py`: все 29 `QShortcut` — через `bind`, легенды под
  таблицами и подсказка боковой панели — из реестра; хак банка с `findChildren` снят.
- `grid_editing.py` (Ins/F9/Del ×4 страницы → один миксин), `widgets.caption()` (66 мест).
- **Preferences** `desktop/preferences.py`: 27 `QSettings()` в 14 файлах → `prefs()`.
- Потоки: закрытая компания не получает фоновый результат (`Session.closed`, тест
  воспроизвёл); `portal_worker.run_on_portal` вместо трёх QThread — поток переживает
  закрытое окно (так падал воркер xdist); AST-тест «фон не трогает виджеты» (31 место, чисто).
- Тесты: одна `no_modal_dialogs` в conftest (маркер `questions("Yes")`); демо-файл один раз
  на процесс + удаление закрытых окон; 135 общих имён → `tests/helpers/` (`pytest_plugins`).
- i18n: `N_()` (~360 мест), обратная проверка «ключ AZ без вызова», 72 мёртвых ключа удалены.
- Ширина колонки отчёта — по выборке (200 строк + итоги) с кэшем.

Замеры: `test_desktop.py` 100,0 с → 7,8 с (setup 3,6 с → 0,05 с; причина — не демо, оно
0,16 с, а 7 400 неудалённых виджетов, которые перекрашивал каждый `theme.apply`); весь
прогон `-n 8` 188 с → 151 с; `layout_columns` на 1 320 строках 52 → 9,6 мс.

Не сделано / при слиянии: `desktop/app.py` создаёт `QSettings()` (файл другой сессии —
исключение `NOT_YET` в `tests/test_preferences.py`); `N_` в `application/`, `reporting/`
(66 ключей, `NOT_MARKED_YET` в `test_i18n.py`); `QTableWidget`/`QTreeWidget` в формах
импорта оставлены — по D133 список с галочками и группами это `QTreeWidget` (`fit_tree`),
перевод на модель не дёшев; Ctrl+S/Ctrl+Enter доп. расходов и складского документа теперь
действуют внутри страницы (было — во всём окне), как у остальных документов.

План декомпозиции окна (не делалось): `CompanyFiles ← OpenPages ← ReportPlaces ← MainWindow`
(2 161 строка, 12 крючков) → `CompanySession` (файл, открыть/закрыть/копии, `prefs`; без Qt-
окна), `PageStack` (страницы по ключу, `came_from`, протокол `Page`), `Navigator` (что
открывается по ключу: фабрика мест и документов, проводка сигналов) и тонкое `MainWindow`,
собирающее их композицией. Нужно: события «компания открыта/закрыта» из `CompanySession`
вместо крючков `_show_company/_drop_pages`; `_make_place` — таблица `ключ → фабрика`;
тесты, которые лезут в `window.pages`/`_activate`, — через `PageStack`.

Решения (тексты — в `docs/decisions/D188-*.md` при слиянии):

- **D1881 «Протокол страницы».** Окно спрашивает у страницы только протокол
  `desktop/page.py::Page`: `key`, `title()`, `is_dirty()`, `save(post)`, `refresh()`,
  `activated()`, `on_postings_changed(doc_id)`. Страница наследует `PageWidget` (пустые
  реализации) и переопределяет нужное; заглушка — `EmptyPage`. «Кого обновить при показе» и
  «кого перечитать после проводки» решает сама страница, окно не перечисляет классы
  (`isinstance`, `getattr` запрещены). `tests/test_page_protocol.py` открывает все места и
  документы демо-компании и проверяет протокол.
- **D1882 «Реестр горячих клавиш».** Клавиши программы — одна таблица
  `desktop/shortcuts.py::KEYS`: id, клавиши, scope (WINDOW — всё окно, PAGE — страница и её
  поля, GRID — только таблица, не в открытой ячейке, TYPED — вводится в таблицу, только в
  легенде) и описание (`tr`). Привязка — `bind(widget, id, slot)`, `QShortcut(` вне реестра
  не пишется; легенды под таблицами — `legend(*ids)`. В одном scope две записи с одними
  клавишами запрещены, у описания есть перевод (`tests/test_shortcuts.py`).
- **D1883 «Preferences».** Всё, что программа помнит для пользователя между запусками,
  — `desktop/preferences.py`: ключ назван один раз, у него тип и значение по умолчанию,
  чтение/запись — методами `Preferences` (`prefs()` — новый объект над тем же QSettings;
  окно оборачивает переданный ему QSettings). Данные компании там не хранятся — они в её
  файле. `QSettings(` в `src` — только в `preferences.py` (`tests/test_preferences.py`).

Проверено: `ruff`, `ruff format`, `pyright` — 0; `pytest -q -n auto` — 1470 passed (151 с), включая test_code_size, test_i18n, test_read_only_ui, test_window_design.
