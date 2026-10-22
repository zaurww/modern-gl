# Modern GL

Бухгалтерская программа (главная книга) в стиле 1С 7.7: проводки Дт/Кт с субконто, несколько компаний, параллельные книги (общая / МСФО / налог). Пользователь общается по-русски.

Начало сессии: прочитать `docs/STATUS.md` (что сделано, что дальше), `docs/DECISIONS.md` (имеет приоритет над `SPEC.md` и `ARCHITECTURE.md`) и `docs/ENGINEERING.md`. В конце сессии — обновить `docs/STATUS.md` и раздел «Долг» в `docs/ENGINEERING.md`, пройти проверки из `docs/CODE_QUALITY.md` (раздел 4); раз в ~5 сессий и перед слиянием большой ветки — полный обзор кода по чек-листу оттуда же.

## Команды
- Тесты: `uv run pytest -q`
- Линтер: `uv run ruff check . && uv run ruff format --check .`
- Типы: `uv run pyright` (тот же движок, что Pylance; должно быть 0 ошибок)
- Программа: `uv run modern-gl` — компании это файлы `*.gl` в «Документы\Modern GL» (`--data <папка>` — другая папка, запоминается); `--demo` добавляет демо-компанию в пустую папку; `--demo-year` — компанию с целым 2026 годом во всех модулях (`demo_year/`)
- Скриншоты для проверки дизайна: `uv run python scripts/screenshots.py <папка>` — после любых изменений UI смотреть их
- Демо в консоли: `uv run python scripts/demo.py`
- Размеры кода (самые большие места): `uv run python tests/test_code_size.py`
- AI-помощник (MCP): `uv run modern-gl-mcp` (только чтение; `--allow-drafts` — AI готовит черновики) — подключение в `docs/ASSISTANT.md`

## Структура
- `src/modern_gl/domain` — деньги, даты, ошибки. Без SQL и Qt.
- `src/modern_gl/application/ledger/` — все операции записи и правила учёта: `Ledger` собран из групп (`companies`, `currencies`, `subconto`, `chart`, `templates`, `documents`, `validation`, `document_import`, `revaluation`, `opening`, `conversion`, `bank`; общее модулей — `module.py`); общие помощники — `application/common.py`.
- `src/modern_gl/application/inventory/` — склад: `Inventory` собран так же из групп (`catalog`, `drafts`, `stock`, `movements`, `sales`, `landed_cost`, `accruals`, `posting`); `model` — константы и dataclass-строки, `amounts` — чистая арифметика.
- `src/modern_gl/reporting/reports.py` — ОСВ, ОСВ по субконто, карточка, анализ счёта (агрегация в SQL); `reporting/report_common.py` — общее отчётов; `reporting/plaintext.py` — журнал для hledger (D79); `reporting/handover.py` — пакет «Передача дел» (D81); `reporting/inventory/` — склад (`choices`, `stock`, `documents`, `costs`, `declarations` — отчёт «Əlavə xərclər», D85).
- `src/modern_gl/assistant` — MCP-сервер для AI (D83): `protocol` (JSON-RPC по stdio), `companies` (снимки файлов), `answers` (отчёты в JSON), `server` (инструменты, `main`); `drafts` + `draft_tools` — черновики от AI (D84, флаг `--allow-drafts`).
- `src/modern_gl/infrastructure` — SQLite, миграции (`migrations/NNNN_*.sql`), импорт CSV, `workspace.py` (файл на компанию).
- `src/modern_gl/desktop` — интерфейс: `main_window/` (`CompanyFiles` — файл компании ← `OpenPages` — стек страниц ← `MainWindow` — какие страницы есть; `sidebar`), `document_page/` (документ: `form`, `rates`, `templates`, `clipboard`), `postings/` (таблица ввода), `cell_editing` (редактирование ячеек как в 1С: списки с поиском, Enter/Tab, поиск в списке `resolve_choice` — для всех таблиц), `journal_page`, `trade_page` (покупки и продажи), `bank_page/` (модуль «Банк», D78: счета по группам → выписки по дням со сверкой → выписка; `levels`, `reconcile`, `dialogs`, `offset_dialog`, `entry/` — строка ввода: `fields`, `choices`, `saving`, `line`) + `bank_operation_page/` (полная форма операции, F2; `form` — поля, группы `bank`, `counterparty`, `lines`, `folded`), `eqaime_import_page` (+ `eqaime_import_form`, `eqaime_portal_loader`) + `portal_login` (e-qaimə с портала, клиент — `infrastructure/etaxes.py`), `inventory_page/` (страница «Склад», D88: `form` — кнопки операций, `stock` — остатки, `movements` — карточка товара, `documents` — все документы, `dialogs`), `inventory_document_page/` (форма покупки, продажи и складских документов), `landed_cost_page/` (доп. расходы) + `landed_cost_report_page` (отчёт по декларациям), `reports_page/` (ОСВ, карточка, план счетов; `table` — таблица отчёта), `directories_page/` (`tags`, `values` — окно элемента), `conversion_page/`, `opening_balances_page` + `opening_postings`, `account_dialog`, `theme` (все цвета и шрифты), `i18n_az.py` (переводы).

## Правила
- **Инженерные правила (D71, D72)** — перед каждой новой функцией пройти чек-лист `docs/ENGINEERING.md`: модульность и масштабируемость (ядро не знает о модулях, модуль — свой пакет и таблицы), архитектура данных (один источник правды, производное пересчитывается, импорт без дублей), структура базы (`company_id NOT NULL`, составные FK, индекс на каждую ссылку, `CHECK`, миграции неизменны), разработка (тест прежде исправления, транзакция на сценарий, CI зелёный). `tests/test_architecture.py` и `tests/test_database.py` должны быть зелёными; исключения в них не добавлять без записи в «Долг». В ответе пользователю о новой функции — одной строкой, затронула ли она эти правила.
- Деньги — только `int` в копейках; никаких `float`.
- Проведённый документ не изменяется и не удаляется; исправление — `Ledger.reverse` (красное сторно).
- Каждый запрос фильтрует по `company_id`; новые таблицы — с составными FK `(company_id, id)`.
- Схема меняется только новой миграцией; старые миграции не редактировать.
- **База за одним модулем (D77):** `sqlite3` импортирует только `infrastructure`; типы `Connection`/`Row`/ошибки — из `infrastructure.db`; SQL — общий для SQLite и PostgreSQL (`string_agg`, не `GROUP_CONCAT`; без `PRAGMA`, `rowid`, `INSERT OR`) — следит `test_architecture.py`.
- **Только просмотр (D80):** компания может быть открыта снимком без права записи (`session.read_only`). Новая кнопка, которая что-то меняет, — через `hide_when_viewing(session.read_only, …)`; форма документа учитывает `session.read_only`; страница при открытии ничего не пишет — следит `tests/test_read_only_ui.py`.
- Любое изменение логики учёта — с тестом, в котором ожидаемые цифры посчитаны вручную.
- Сообщения об ошибках для пользователя — по-русски.
- **Размер кода** (D70, `docs/CODE_QUALITY.md`): модуль — одна задача; большая страница — форма (`form.py`: поля строятся методами) + группы-классы по задачам, общие вызовы — «крючки» в форме; пределы — модуль 600 строк, класс 500, функция 80, их проверяет `tests/test_code_size.py`. Список долга `OVER_LIMIT` пуст и не пополняется — сначала разделить. Крупный модуль превращается в пакет с тем же именем, `__init__` реэкспортирует прежний API; перенос кода — отдельным коммитом, без изменения логики.
- **Дизайн — главный приоритет** (ориентир: Things от Cultured Code): светло, много воздуха, боковая панель вместо вкладок, крупные заголовки, один акцентный синий, без сеток «как в Excel». Цвета и шрифты — только через `desktop/theme.py`.
- UI: `src/modern_gl/desktop` (PySide6). Никакого SQL в виджетах — только `application/queries.py`, `application/catalog.py`, `reporting`.
- В тестах UI модальные диалоги подменяются (`no_modal_dialogs`), иначе тест зависнет.
- **Языки**: интерфейс азербайджанский (по умолчанию) и русский. Любой текст для пользователя — через `tr("русский текст {x}", x=...)`; перевод добавить в `i18n_az.py` (`tests/test_i18n.py` упадёт, если забыть). Шаблон плана счетов — в двух файлах `templates/chart_1c77_{az,ru}.csv` с одинаковой структурой.
- Поиск по справочникам — через `i18n.fold` (İ/ı/ş/ç/ə… = i/s/c/e…).
- `QTest.keyClicks` в PySide под Windows падает на кириллице и азербайджанских буквах — в тестах вводить через `type_text()`.
- Если программа запущена, `uv run` не может обновить `modern-gl.exe` — использовать `uv run --no-sync` или закрыть программу.
