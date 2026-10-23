# Как устроена программа

Текущее устройство (сессия 40). Зачем и в каких рамках — `docs/CONCEPT.md`; правила для
нового кода — `docs/ENGINEERING.md`; список пакетов и файлов — «Структура» в `CLAUDE.md`.
Первые черновики (v0.1, англ.) — в `docs/history/`, они устарели.

## 1. Слои

```text
desktop (PySide6)          страницы, формы, таблицы — без SQL и без правил учёта
   │  Session: conn, ledger, catalog, read(), notify
application                сценарии записи (Ledger, Inventory) и чтение для форм (queries, catalog)
reporting                  отчёты — только чтение, агрегация в SQL
assistant                  MCP-сервер для AI — те же application/reporting
   │
domain                     деньги, даты, периоды, формулы — без SQL и Qt
infrastructure             SQLite (sqlite3 — только здесь: db.py, копии, файлы), миграции,
                           файлы компаний, копии, CSV/Excel, порталы (cbar, e-taxes)
```

Зависимости — сверху вниз. Следят `tests/test_architecture.py` (слои, ядро не знает
модулей, нет SQL в виджетах, окно не открывает транзакцию) и `tests/test_database.py`.

## 2. Запись: `Ledger` и модули
- **`Ledger`** (`application/ledger/`) — ядро: компании, валюты, справочники, план счетов,
  шаблоны, документы и проводки, проверки при проведении, импорт, переоценка, начальные
  остатки. Собран из групп-классов над одним соединением (`ledger.documents`, …), снаружи —
  один объект.
- **Модули — отдельные объекты над тем же соединением:** `ledger.bank`,
  `ledger.conversion`, `ledger.eqaime`; склад — `Inventory` (`application/inventory/`, тоже
  из групп). Общее модулей — `ledger/module.py` (запись GL-документа модуля).
- **Сценарий = один метод = одна транзакция** (`db.transaction`). Ошибка — `LedgerError`
  с текстом для пользователя; половины документа не остаётся.
- **Входы — dataclass** (`ledger/inputs.py`), не словари.
- **Журнал действий** `audit_events` — только добавление: каждое изменение, копия прежнего
  при правке проведённого, автор и причина (D82, D96).

## 3. Как ядро и модули узнают друг о друге
Ядро не читает таблиц модулей. Связь — через несколько общих точек:

| Точка | Что даёт | Где |
|---|---|---|
| `document_owners` (представление) | Чей GL-документ: модуль создал (`made`) или взял (`uses`); журнал не даёт его править | миграция 0032 + миграция модуля, `explain_owner` |
| `rebuild_postings(company_id, since)` | Модуль строит свои проводки заново с даты | `application/rebuild.py`, `tests/test_rebuild.py` |
| `attention_source` | Строки «Diqqət tələb edir» на «Bu gün» | `reporting/overview.py` |
| Команды и места Ctrl+K | Что предлагает палитра | `desktop/main_window/commands.py` |
| Роли счетов | Счёт для операции модуля (НДС, авансы, транзит) — по роли или типу | `default_accounts.py`, `account_role` |
| `SECTIONS` / `STOCK_SECTIONS` | Место модуля в боковой панели и в режиме «Только склад» | `main_window/sidebar.py` |

Новый модуль: свой пакет в `application/`, свои таблицы своей миграцией, свои страницы в
`desktop/`, и подключение к точкам выше.

## 4. Данные
- **Файл компании** — SQLite `<Название>.gl`; `infrastructure/workspace.py` открывает,
  создаёт (через `.part`), запоминает внешние файлы; `backup.py` — копии через Backup API
  с `integrity_check`; режим просмотра — снимок в памяти (`db.open_snapshot`, D80).
- **Схема** — только миграциями `migrations/NNNN_*.sql`, подряд, написанные не меняются
  (хэши в `test_database.py`); каждая — в своей транзакции с `foreign_key_check`.
- **Каждая таблица** — `company_id NOT NULL`, составные FK `(company_id, id)`, индекс на
  ссылку, `CHECK` на перечисления и даты (исключения — «Долг» в `ENGINEERING.md`).
- **Проводки** (`documents` + `postings`): пара Дт/Кт, сумма в копейках, до 3 субконто на
  сторону, валюта и сумма в ней, слой. Остатки не хранятся — считаются запросом.
- **Хранимое производное** — себестоимость и движения склада: пересчитываются одной
  процедурой задним числом (`inventory/rebuild`), сверка «пересчёт = хранимое» в тестах.
- **SQL общий для SQLite и PostgreSQL** (D77): `string_agg`, без `PRAGMA`/`rowid`/`INSERT OR`.

## 5. Чтение и отчёты
- `application/queries.py`, `catalog.py` — то, что нужно формам (списки, «как в прошлый
  раз»); `reporting/` — отчёты: ОСВ, карточка, анализ (`reports.py`), баланс, ОПиУ, ДДС,
  сравнение книг, колонки по периодам, склад, e-qaimə, «Bu gün», hledger, «Передача дел».
- Агрегация — в SQL с индексом; без «прочитать всё в Python» и без запроса на строку.
- Книга в отчёте = набор слоёв (`report_common.BOOKS`).

## 6. Интерфейс
- **Окно:** `CompanyFiles` (файл компании) ← `OpenPages` (стек страниц, Esc — назад) ←
  `ReportPlaces` (как открываются отчёты) ← `MainWindow` (какие страницы есть); боковая панель вместо вкладок.
- **Страница читает в два шага:** `fetch(conn)` — только SQL, `present(data)` — заполнить;
  через `Session.read` — у большой компании в фоновом потоке (`desktop/background.py`).
  Страница при открытии ничего не пишет.
- **Большая страница** — форма (`form.py`, поля строятся методами) + группы-классы по
  задачам; общие вызовы — «крючки» формы (D70).
- **Ввод как в 1С:** `cell_editing` (списки с поиском, Enter/Tab, `resolve_choice`),
  `PickBox` в шапках, `PeriodField`/`DateEdit` с коротким вводом (`domain/period_input.py`).
- **Вид** — только через `desktop/theme/` (палитры, Inter, `css`), иконки Lucide
  (`desktop/icons.py`); `PageHeader`: одна синяя кнопка + «⋯» (D86).
- **Тексты** — `tr("русский {x}")`, перевод в `i18n_az.py`; поиск — `i18n.fold`.
- **Только просмотр** — `session.read_only`, кнопки записи через `hide_when_viewing`.

## 7. AI-помощник
`modern-gl-mcp` (`assistant/`): JSON-RPC по stdio, каждая компания — снимком только для
чтения; с `--allow-drafts` — черновики через тот же `Ledger`, автор «AI · Claude» (D83, D84).

## 8. Проверки
| Что | Чем |
|---|---|
| Учёт | тесты с цифрами вручную, `tests/conftest.py`, демо-год `tests/test_demo_year.py` |
| Слои и границы модулей | `test_architecture.py` |
| Схема | `test_database.py` |
| Размер кода (600/500/80) | `test_code_size.py` |
| Размер документов | `test_docs_size.py` (D109) |
| Переводы | `test_i18n.py` |
| Режим просмотра | `test_read_only_ui.py` |
| Перестроение модулей | `test_rebuild.py` |
| Вид | `scripts/screenshots.py` — смотреть глазами |
| Скорость | `scripts/benchmark.py` (100 000 проводок: ОСВ 0,5 с) |
