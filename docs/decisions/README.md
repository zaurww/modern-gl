# Решения

Одно решение — один файл: статус, дата, контекст, решение (слова пользователя), последствия
(где живёт в коде). Только добавление: номера не переиспользуются, отменённое получает статус
«заменено D<n>». Найти `D72` — `ls docs/decisions | grep D072`, по слову — `grep -rl слово
docs/decisions`. Новое решение в ветке — `D-new-<slug>.md`, при слиянии — следующий номер
`master` (`CLAUDE.md`, «Параллельные сессии»). Ещё не решённое — `OPEN.md`.

Таблица ниже генерируется: `uv run python scripts/decisions_index.py`, руками не править.

| # | Решение | Статус | Файл |
|---|---|---|---|
| D1 | Проводка = пара Дт/Кт | принято | [D001-posting-debit-credit-pair.md](D001-posting-debit-credit-pair.md) |
| D2 | Субконто — часть ядра | принято | [D002-subconto-in-core.md](D002-subconto-in-core.md) |
| D3 | Деньги — целые копейки | принято | [D003-money-integer-kopecks.md](D003-money-integer-kopecks.md) |
| D4 | Один файл SQLite на все компании | заменено D18 | [D004-one-sqlite-file.md](D004-one-sqlite-file.md) |
| D5 | Исправление проведённого — красное сторно | принято | [D005-red-storno-correction.md](D005-red-storno-correction.md) |
| D6 | Развёрнутое сальдо | принято | [D006-expanded-balance.md](D006-expanded-balance.md) |
| D7 | Слой ≠ книга | принято | [D007-layer-vs-book.md](D007-layer-vs-book.md) |
| D8 | Без выгрузки из 1С 7.7 | принято | [D008-no-1c-export.md](D008-no-1c-export.md) |
| D9 | Чистый `sqlite3` + SQL-миграции по `PRAGMA user_version` | принято | [D009-plain-sqlite-migrations.md](D009-plain-sqlite-migrations.md) |
| D10 | Номер документа — сквозной по компании | принято | [D010-document-number-sequence.md](D010-document-number-sequence.md) |
| D11 | План счетов по умолчанию — шаблон «1c77» | принято | [D011-chart-template-1c77.md](D011-chart-template-1c77.md) |
| D12 | Интерфейс на азербайджанском и русском | принято | [D012-interface-az-ru.md](D012-interface-az-ru.md) |
| D13 | Нули в отчётах не показываются | принято | [D013-zeros-hidden-in-reports.md](D013-zeros-hidden-in-reports.md) |
| D14 | Класс счёта (уровень 1 классификации для отчётности) | принято | [D014-account-class.md](D014-account-class.md) |
| D15 | Редактирование плана счетов | принято | [D015-chart-editing.md](D015-chart-editing.md) |
| D16 | Банки — через субконто «Банковские счета» на 51 | принято | [D016-banks-as-subconto.md](D016-banks-as-subconto.md) |
| D17 | Вид счёта (A / P / AP) убран | принято | [D017-account-kind-removed.md](D017-account-kind-removed.md) |
| D18 | Отдельный файл на каждую компанию | принято | [D018-file-per-company.md](D018-file-per-company.md) |
| D19 | Исправление ошибок как в 1С, но с аудитом | принято | [D019-corrections-with-audit.md](D019-corrections-with-audit.md) |
| D20 | Раздел «Справочники» (Soraqçalar) | принято | [D020-directories-section.md](D020-directories-section.md) |
| D21 | План счетов по умолчанию — короткий «classic» | принято | [D021-chart-template-classic.md](D021-chart-template-classic.md) |
| D22 | Код счёта необязателен | принято | [D022-account-code-optional.md](D022-account-code-optional.md) |
| D23 | Шаблоны операций: одна сумма S + формулы строк | принято | [D023-operation-templates-formulas.md](D023-operation-templates-formulas.md) |
| D24 | Python + PySide6 + SQLite остаются стеком локальной однопользовательской версии | принято | [D024-python-pyside-sqlite-stack.md](D024-python-pyside-sqlite-stack.md) |
| D25 | Коммерческий целевой пользователь — бухгалтер-консультант: один сотрудник ведёт несколько фирм | принято | [D025-target-user-consultant.md](D025-target-user-consultant.md) |
| D26 | Склад — отдельный количественно-суммовой регистр, атомарно связанный с GL | принято | [D026-inventory-register.md](D026-inventory-register.md) |
| D27 | Складской документ имеет собственный жизненный цикл и карточку | принято | [D027-stock-document-lifecycle.md](D027-stock-document-lifecycle.md) |
| D28 | Валютный учёт — признак счёта, три режима | принято | [D028-currency-account-modes.md](D028-currency-account-modes.md) |
| D29 | Договоры принадлежат контрагентам | принято | [D029-contracts-belong-counterparty.md](D029-contracts-belong-counterparty.md) |
| D30 | Цель — удобный и гибкий инструмент для себя, не продажа | принято | [D030-tool-for-self.md](D030-tool-for-self.md) |
| D31 | Регламентированная отчётность — отдельные пакеты, GL не меняется | принято | [D031-regulated-reporting-separate.md](D031-regulated-reporting-separate.md) |
| D32 | Проведённый документ правится на месте, как в 1С | принято | [D032-posted-document-edit-in-place.md](D032-posted-document-edit-in-place.md) |
| D33 | Landed cost — по образцу ERPNext Landed Cost Voucher, без зашитых номеров счетов | принято | [D033-landed-cost-voucher.md](D033-landed-cost-voucher.md) |
| D34 | Счета автоматических проводок — «роли счетов» компании, не коды | принято | [D034-account-roles.md](D034-account-roles.md) |
| D35 | Тип счёта — смысл счёта при любом коде | принято | [D035-account-type.md](D035-account-type.md) |
| D36 | VÖEN контрагента; нерезидент без VÖEN | принято | [D036-counterparty-tax-id.md](D036-counterparty-tax-id.md) |
| D37 | Конвертация валюты — отдельный документ «Конвертация валюты», не шаблон операции | принято | [D037-currency-conversion-document.md](D037-currency-conversion-document.md) |
| D38 | E-qaimə — номер в строке проводки | принято | [D038-eqaime-number-in-posting.md](D038-eqaime-number-in-posting.md) |
| D39 | Начальные остатки — один специальный документ GL на компанию | принято | [D039-opening-balances-document.md](D039-opening-balances-document.md) |
| D40 | Начальные остатки — одна таблица, разница на счёте 00 | принято | [D040-opening-balances-table.md](D040-opening-balances-table.md) |
| D41 | Тип счёта «ƏDV depozit hesabı» (`vat_deposit`, актив; миграция 0021) | принято | [D041-vat-deposit-account-type.md](D041-vat-deposit-account-type.md) |
| D42 | Продажа (Satış) — вид складского документа `sale`, услуга — строка без товара | принято | [D042-sale-document.md](D042-sale-document.md) |
| D43 | Покупка (Alış) услуг и ОС — строка поступления без товара | принято | [D043-purchase-services-assets.md](D043-purchase-services-assets.md) |
| D44 | Раздел «Покупки и продажи» (Alış və satış) отдельно от склада | принято | [D044-trade-section.md](D044-trade-section.md) |
| D45 | Импорт e-qaimə с портала — внутри программы, только черновиками | принято | [D045-eqaime-import-drafts.md](D045-eqaime-import-drafts.md) |
| D46 | «Alış» и «Satış» — два отдельных раздела | принято | [D046-purchase-sale-sections.md](D046-purchase-sale-sections.md) |
| D47 | Модуль «Банк» (Bank) — банковская операция как документ модуля, сначала ручной ввод | принято | [D047-bank-module.md](D047-bank-module.md) |
| D48 | «Сохранить как» для компании | принято | [D048-save-company-as.md](D048-save-company-as.md) |
| D49 | Клавиатура прежде мыши — общий принцип ввода | принято | [D049-keyboard-before-mouse.md](D049-keyboard-before-mouse.md) |
| D50 | Договор (müqavilə) необязателен | принято | [D050-contract-optional.md](D050-contract-optional.md) |
| D51 | E-qaimə в оплате — из списка неоплаченных | принято | [D051-eqaime-from-unpaid-list.md](D051-eqaime-from-unpaid-list.md) |
| D52 | Отчёты — по Jon Moon (Clarity & Impact) | принято | [D052-reports-jon-moon.md](D052-reports-jon-moon.md) |
| D53 | E-qaimə «Təsdiq gözləyir» и сверка с порталом | принято | [D053-eqaime-pending-reconciliation.md](D053-eqaime-pending-reconciliation.md) |
| D54 | Ввод с клавиатуры: Enter = Tab, ячейка всегда открыта, новое имя — из списка | принято | [D054-enter-as-tab-cells.md](D054-enter-as-tab-cells.md) |
| D55 | Ввод одинаковый во всех формах, как в журнале | принято | [D055-same-entry-everywhere.md](D055-same-entry-everywhere.md) |
| D56 | Боковая панель — разделы по назначению | принято | [D056-sidebar-sections.md](D056-sidebar-sections.md) |
| D57 | Период в окнах портала — кнопками | принято | [D057-portal-period-buttons.md](D057-portal-period-buttons.md) |
| D58 | Строка без товара не идёт на складской счёт; «Расходы по партии» → «Дополнительные расходы» | принято | [D058-non-stock-line-expense.md](D058-non-stock-line-expense.md) |
| D59 | Удаление ошибочно введённого счёта и элемента справочника | принято | [D059-delete-mistaken-account-item.md](D059-delete-mistaken-account-item.md) |
| D60 | Группы (папки) в справочниках, как в 1С | принято | [D060-directory-groups.md](D060-directory-groups.md) |
| D61 | Аналитика продаж — субконто на счетах продажи; форма спрашивает его сама | принято | [D061-sales-analytics-subconto.md](D061-sales-analytics-subconto.md) |
| D62 | Счёт комиссии банка выбирается в модуле «Банк» | принято | [D062-bank-commission-account.md](D062-bank-commission-account.md) |
| D63 | Параллельные книги включаются на компанию; без них книги не видно | принято | [D063-parallel-books-per-company.md](D063-parallel-books-per-company.md) |
| D64 | Метки элементов справочников — для отчётов «по признаку», без субсчетов | принято | [D064-directory-item-tags.md](D064-directory-item-tags.md) |
| D65 | Расход за прошлый месяц по поздней e-qaimə — через счёт 76H «Начисленные расходы» | принято | [D065-late-eqaime-expense-76h.md](D065-late-eqaime-expense-76h.md) |
| D66 | Форма банковской операции — одна колонка в порядке ввода | принято | [D066-bank-operation-form-column.md](D066-bank-operation-form-column.md) |
| D67 | E-qaimə в оплате — не только из проведённых документов | принято | [D067-eqaime-payment-any-document.md](D067-eqaime-payment-any-document.md) |
| D68 | Форма «Банк» — путь курсора только по тому, что меняется | принято | [D068-bank-form-cursor-path.md](D068-bank-form-cursor-path.md) |
| D69 | ƏDV депозит в форме оплаты — две операции из одной формы | принято | [D069-vat-deposit-two-operations.md](D069-vat-deposit-two-operations.md) |
| D70 | Модуль — одна задача; крупный модуль делится на пакет | принято | [D070-module-one-task.md](D070-module-one-task.md) |
| D71 | Модульность и масштабируемость — постоянная концепция | принято | [D071-modularity-scalability.md](D071-modularity-scalability.md) |
| D72 | Лучшие практики данных, базы и разработки — те же постоянные правила | принято | [D072-data-db-dev-practices.md](D072-data-db-dev-practices.md) |
| D73 | Статус документа — не похож на чекбокс; черновики покупок и продаж проводятся разом | принято | [D073-document-status-not-checkbox.md](D073-document-status-not-checkbox.md) |
| D74 | Полная проверка базы — на каждой резервной копии | принято | [D074-full-db-check-on-backup.md](D074-full-db-check-on-backup.md) |
| D75 | Владелец GL-документа — представление `document_owners`, ядро читает только его | принято | [D075-document-owners-view.md](D075-document-owners-view.md) |
| D76 | Счёт затрат в покупке подставляется «как в прошлый раз» и в форме | принято | [D076-purchase-expense-account-last.md](D076-purchase-expense-account-last.md) |
| D77 | Движок базы знает только `infrastructure`; SQL — общий для SQLite и PostgreSQL | принято | [D077-db-engine-infrastructure-only.md](D077-db-engine-infrastructure-only.md) |
| D78 | «Банк» — выписки по дням, ввод строками, карты как счета | принято | [D078-bank-statements-by-day.md](D078-bank-statements-by-day.md) |
| D79 | Журнал проводок в текстовом формате hledger — только выгрузка | принято | [D079-hledger-plaintext-export.md](D079-hledger-plaintext-export.md) |
| D80 | Режим «только просмотр»: снимок файла в памяти | принято | [D080-read-only-snapshot.md](D080-read-only-snapshot.md) |
| D81 | «Передача дел…» — вся компания текстом в zip | принято | [D081-handover-zip.md](D081-handover-zip.md) |
| D82 | Кто ввёл и кто провёл документ — из журнала действий | принято | [D082-who-entered-who-posted.md](D082-who-entered-who-posted.md) |
| D83 | AI-помощник — MCP-сервер, сначала только чтение | принято | [D083-ai-assistant-mcp.md](D083-ai-assistant-mcp.md) |
| D84 | Черновики от AI — только черновики, только через `Ledger`, автор — «AI · клиент» | принято | [D084-ai-drafts-only.md](D084-ai-drafts-only.md) |
| D85 | Отчёт «Əlavə xərclər» — по декларации (поступлению), полная стоимость на сейчас | принято | [D085-landed-cost-report.md](D085-landed-cost-report.md) |
| D86 | Дизайн-система: эволюция Things, «вау» без шума | принято | [D086-design-system-things.md](D086-design-system-things.md) |
| D87 | «Провести черновики» спрашивает, куда идут строки без счёта | принято | [D087-post-drafts-missing-accounts.md](D087-post-drafts-missing-accounts.md) |
| D88 | Склад — самостоятельный модуль; страница «Anbar» объясняет себя сама | принято | [D088-inventory-standalone-module.md](D088-inventory-standalone-module.md) |
| D89 | Оборотные и долгосрочные — по типу счёта | принято | [D089-current-vs-noncurrent-by-type.md](D089-current-vs-noncurrent-by-type.md) |
| D90 | Режим компании «Только склад»: бухгалтерия ведётся, но не видна | принято | [D090-stock-only-mode.md](D090-stock-only-mode.md) |
| D91 | «Mədaxil» — поступление товара без покупки, по причине | принято | [D091-medaxil-receipt-reason.md](D091-medaxil-receipt-reason.md) |
| D92 | D86 доделан: тема «как в системе», тост с «Geri al», «Bu gün», Ctrl+K | принято | [D092-d86-finished-theme-undo.md](D092-d86-finished-theme-undo.md) |
| D93 | Долг кода 2, 6, 9–11 погашен: модули — объекты, сценарий — один метод, правила — в application, счета — по типу, большие компании — в фоне | принято | [D093-code-debt-modules-objects.md](D093-code-debt-modules-objects.md) |
| D94 | Быстрая строка: число на стороне Кт — всегда сумма; «как в прошлый раз» | принято | [D094-fast-entry-credit-amount.md](D094-fast-entry-credit-amount.md) |
| D95 | Закрытие периода — окно в меню компании и в Ctrl+K | принято | [D095-period-closing-window.md](D095-period-closing-window.md) |
| D96 | Причина изменения — в журнале действий; «История изменений» документа | принято | [D096-change-reason-audit.md](D096-change-reason-audit.md) |
| D97 | Резервные копии на виду и вторая папка | принято | [D097-backups-visible-second-folder.md](D097-backups-visible-second-folder.md) |
| D98 | Сравнение книг: общий учёт ↔ МСФО ↔ налог на дату | принято | [D098-compare-books.md](D098-compare-books.md) |
| D99 | Финансовая отчётность по типам счетов: Баланс и Прибыли и убытки | принято | [D099-financial-statements-by-type.md](D099-financial-statements-by-type.md) |
| D100 | Движение денежных средств — прямым методом по типу корр. счёта | принято | [D100-cash-flow-direct-method.md](D100-cash-flow-direct-method.md) |
| D101 | Модуль умеет перестроить свои проводки с даты — правило для всех модулей | принято | [D101-module-rebuild-postings.md](D101-module-rebuild-postings.md) |
| D102 | Прибыли и убытки: расход — там, где он возник; строка раскрывается до статьи и документа | принято | [D102-pnl-expense-where-arises.md](D102-pnl-expense-where-arises.md) |
| D103 | Полосы (зебра) в таблицах — по желанию, по умолчанию выключены | принято | [D103-table-zebra-optional.md](D103-table-zebra-optional.md) |
| D104 | Отчёт «для Excel»: плоская таблица, числа — числами | принято | [D104-excel-flat-report.md](D104-excel-flat-report.md) |
| D105 | Период — одно поле с быстрым вводом, как в Todoist; одно и то же на всех отчётах | принято | [D105-period-single-field.md](D105-period-single-field.md) |
| D106 | «Уют» — правило для каждой новой функции | принято | [D106-comfort-rule.md](D106-comfort-rule.md) |
| D107 | Колонки отчёта: по месяцам, по кварталам, сравнение с периодом — концепция | принято | [D107-report-columns-periods.md](D107-report-columns-periods.md) |
| D108 | ОПиУ без повторов счёта; расход на 46 — себестоимость; Esc не открывает соседнюю страницу | принято | [D108-pnl-no-repeats-cost-46.md](D108-pnl-no-repeats-cost-46.md) |
| D109 | Документы — короткие, рамка — отдельно | принято | [D109-short-documents.md](D109-short-documents.md) |
| D110 | Детализация как в 1С и второй счёт в групповом проведении | принято | [D110-detail-like-1c-second-account.md](D110-detail-like-1c-second-account.md) |
| D111 | Сейчас — для себя; дальше возможны команда и продажа | принято | [D111-team-and-sale-later.md](D111-team-and-sale-later.md) |
| D112 | ƏDV DH — с портала, не из Excel | принято | [D112-vat-deposit-from-portal.md](D112-vat-deposit-from-portal.md) |
| D113 | VÖEN компании — сверка с порталом перед любой загрузкой | принято | [D113-company-tax-id-check.md](D113-company-tax-id-check.md) |
| D114 | «Все отчёты» — одно место для всех отчётов; закреплённые — в боковой панели | принято | [D114-all-reports-hub.md](D114-all-reports-hub.md) |
| D115 | ƏDV DH с портала — за период, повтор с вопросом | принято | [D115-vat-deposit-period-repeat.md](D115-vat-deposit-period-repeat.md) |
| D116 | Колонки отчёта выбирает пользователь; редкие скрыты | принято | [D116-report-columns-user-choice.md](D116-report-columns-user-choice.md) |
| D117 | ƏDV DH с портала — сначала просмотр, итог в окне | принято | [D117-vat-deposit-preview.md](D117-vat-deposit-preview.md) |
| D118 | ƏDV DH — сверка с порталом за период | принято | [D118-vat-deposit-reconciliation.md](D118-vat-deposit-reconciliation.md) |
| D119 | Покупка «ждёт e-qaimə» — товар пришёл раньше документов | принято | [D119-purchase-awaiting-eqaime.md](D119-purchase-awaiting-eqaime.md) |
| D120 | Какие проводки номера e-qaimə считаются — одно правило на два назначения | принято | [D120-eqaime-postings-rule.md](D120-eqaime-postings-rule.md) |
| D121 | Склад: сначала проверить и сравнить, потом отчёты; первый товар — без настройки | принято | [D121-inventory-check-first.md](D121-inventory-check-first.md) |
| D122 | Слои — только сверху вниз; вход для человека — README | принято | [D122-layers-downwards-readme.md](D122-layers-downwards-readme.md) |
| D123 | Модуль — свой пакет целиком, чтение и запись | принято | [D123-module-whole-package.md](D123-module-whole-package.md) |
| D124 | Турагентство и проекты — справочник «Sifarişlər» третьим субконто, не договор и не модуль | принято | [D124-orders-subconto-projects.md](D124-orders-subconto-projects.md) |
| D125 | «Анализ субконто» — элемент справочника по всем счетам сразу | принято | [D125-subconto-analysis.md](D125-subconto-analysis.md) |
| D126 | «Карточка субконто» — проводки элемента по всем счетам, с остатком | принято | [D126-subconto-card.md](D126-subconto-card.md) |
| D127 | Дизайн отчётов — один концепт `docs/DESIGN.md`; ОСВ — вариант B; сетка по умолчанию | принято | [D127-report-design-concept.md](D127-report-design-concept.md) |
| D128 | ОПиУ по IFRS 18, без ƏDV; отложенный налог — свои типы счетов | принято | [D128-pnl-ifrs18-deferred-tax.md](D128-pnl-ifrs18-deferred-tax.md) |
| D129 | Выбор дат — капсула периода и один календарь дней | принято | [D129-period-capsule-calendar.md](D129-period-capsule-calendar.md) |
| D130 | Для разработчиков: формат обмена документами, публичный API, командная строка | принято | [D130-developer-api-exchange.md](D130-developer-api-exchange.md) |
| D131 | Параллельные сессии — каждая в своём worktree, номера при слиянии, свои файлы вместо общего конца | принято | [D131-parallel-sessions-worktrees.md](D131-parallel-sessions-worktrees.md) |
| D132 | «Банк» — вход одним щелчком, Esc назад, период у счёта, колонки по содержимому | принято | [D132-bank-one-click-navigation.md](D132-bank-one-click-navigation.md) |
| D133 | Три вида таблиц: список, отчёт, ввод | принято | [D133-three-table-kinds.md](D133-three-table-kinds.md) |
| D134 | Две книги: `common` в налоговом стиле, МСФО — слоем корректировок; временная разница — проводка в слое, постоянная — признак | принято | [D134-two-books-tax-ifrs.md](D134-two-books-tax-ifrs.md) |
| D135 | Как решать спорное: как делает пользователь сегодня, не усложнять обычный день, обратимое не решать заранее, ждать реального случая | принято | [D135-how-to-decide-disputed.md](D135-how-to-decide-disputed.md) |
| D136 | «Расход за» — у строки покупки; диапазон месяцев делит строку поровну; «Разделить строку» F8 | принято | [D136-expense-period-purchase-line.md](D136-expense-period-purchase-line.md) |
| D137 | Код товарной группы e-qaimə — хранить строки портала, отчёт по кодам при надобности | принято | [D137-eqaime-goods-group-code.md](D137-eqaime-goods-group-code.md) |
| D138 | Модуль ƏDV: зачёт ƏDV покупок по версии правил своего года; отчёт «ƏDV к зачёту» | принято | [D138-vat-module-rules-by-year.md](D138-vat-module-rules-by-year.md) |
| D139 | «Реестр e-qaimə» — отдельный отчёт модуля ƏDV, а не расширение «E-qaimələr» | принято | [D139-eqaime-register-report.md](D139-eqaime-register-report.md) |
| D140 | Правка e-qaimə — к периоду самой e-qaimə; уточнённая декларация — разницей на дату подачи | принято | [D140-eqaime-correction-period.md](D140-eqaime-correction-period.md) |
| D141 | Реестр знает, сверен ли его период с порталом; отметка «сверено» помнит книгу | принято | [D141-register-reconciled-mark.md](D141-register-reconciled-mark.md) |
| D142 | ƏDV продаж — по каждому поступлению денег: большее из ƏDV на депозите и ƏDV поступившей стоимости | принято | [D142-vat-sales-per-receipt.md](D142-vat-sales-per-receipt.md) |
| D143 | Сверка поступлений с e-qaimə — по покупателю, аванс раскладывается на e-qaimə по старшинству; предупреждения, где ƏDV начислен не так | принято | [D143-receipts-eqaime-reconciliation.md](D143-receipts-eqaime-reconciliation.md) |
| D144 | Сверка оплат поставщикам с e-qaimə — как у покупателей (D143); предупреждение — ƏDV оплаченной e-qaimə не зачтён | принято | [D144-supplier-payments-reconciliation.md](D144-supplier-payments-reconciliation.md) |
| D145 | ƏDV поставщику с расчётного счёта — признак у оплаты; аванс на депозит платит ƏDV первым; «плательщик ƏDV с даты» | принято | [D145-vat-to-supplier-flag.md](D145-vat-to-supplier-flag.md) |
| D146 | Выписка банка из файла — шаблон на банк (первым Kapital Bank); проводится только уверенное, остальное — черновик с причиной | принято | [D146-bank-statement-file-templates.md](D146-bank-statement-file-templates.md) |
| D147 | Новый элемент вида — с тестом на соответствие дизайну; окна загрузки — один каркас | принято | [D147-design-test-new-view.md](D147-design-test-new-view.md) |
| D148 | Обновление файла компании — всё или ничего; старая программа не трогает новый файл; каждая схема — тест на настоящем файле | принято | [D148-company-file-upgrade-atomic.md](D148-company-file-upgrade-atomic.md) |
| D149 | Правила учёта держит и сам файл: деньги только целые, закрытый период неизменен | принято | [D149-file-holds-accounting-rules.md](D149-file-holds-accounting-rules.md) |
| D150 | Склад: отчёты — ведомость, карточка товара, валовая прибыль; операции — после решения | принято | [D150-inventory-reports.md](D150-inventory-reports.md) |
| D151 | Ввод склада: контрагент в шапке, инвентаризация, все товары на «Склад» | принято | [D151-inventory-entry-party-stock-count.md](D151-inventory-entry-party-stock-count.md) |
| D152 | Язык документов — настройка компании, а не интерфейса | принято | [D152-document-language-company.md](D152-document-language-company.md) |
| D153 | Возвраты поставщику и от покупателя — свои виды документов, проводки обратные, с номером e-qaimə возврата | принято | [D153-inventory-returns.md](D153-inventory-returns.md) |
| D154 | Минимальный остаток; продажа раньше прихода — без минуса | принято | [D154-minimum-stock-sale-before-receipt.md](D154-minimum-stock-sale-before-receipt.md) |
| D155 | Файл не принимает несуществующий день, нечитаемое время, флаг не 0/1 и тип счёта чужого класса | принято | [D155-schema-value-checks.md](D155-schema-value-checks.md) |
| D156 | Строка покупки — «Товар» или «Услуга»; для чего купленное — решает счёт товара | принято | [D156-purchase-line-goods-or-service.md](D156-purchase-line-goods-or-service.md) |
| D157 | Решения — файл на решение в формате ADR | принято | [D157-adr-decision-files.md](D157-adr-decision-files.md) |
| D158 | Обработчик падений и журнал программы | принято | [D158-crash-log.md](D158-crash-log.md) |
| D159 | Чужой SQLite-файл не принимается; WAL после миграций; «файл занят» | принято | [D159-foreign-file.md](D159-foreign-file.md) |
| D160 | Вложенная транзакция — savepoint | принято | [D160-nested-savepoint.md](D160-nested-savepoint.md) |
| D161 | Инструменты разработки: CI на Windows, покрытие, свойства, снимки, релиз | принято | [D161-dev-tooling.md](D161-dev-tooling.md) |
| D162 | Модули — композиция, не наследование ядра (уточняет D123) | принято | [D162-module-composition.md](D162-module-composition.md) |
| D163 | Проводка как значение — PostingRecord | принято | [D163-posting-record.md](D163-posting-record.md) |
| D164 | Протокол страницы | принято | [D164-page-protocol.md](D164-page-protocol.md) |
| D165 | Реестр горячих клавиш | принято | [D165-shortcuts-registry.md](D165-shortcuts-registry.md) |
| D166 | Настройки пользователя — Preferences | принято | [D166-preferences.md](D166-preferences.md) |
| D167 | Ruff строже: bandit, имена, pytest, без print и закомментированного кода | принято | [D167-ruff-strict.md](D167-ruff-strict.md) |
| D168 | Журнал читается порциями, поиск — в запросе | принято | [D168-journal-paging.md](D168-journal-paging.md) |
| D169 | Сетевая или облачная папка: без WAL, предупреждение и замок файла | принято | [D169-network-folder-lock.md](D169-network-folder-lock.md) |
| D170 | Типы: тесты под pyright, ядро — strict, докстринги ядра обязательны | принято | [D170-pyright-strict-core.md](D170-pyright-strict-core.md) |
| D171 | Главное окно — композиция частей, а не цепочка наследования | принято | [D171-main-window-composition.md](D171-main-window-composition.md) |
| D172 | Строка покупки — «Куда»: «Склад» или «Счёт»; выбранный счёт идёт в пустые строки | принято (уточняет D156) | [D172-purchase-line-where.md](D172-purchase-line-where.md) |
| D173 | Много строк покупки разом: выделенные строки берут одно значение, ОС — по названиям строк | принято (уточняет D172) | [D173-line-objects.md](D173-line-objects.md) |
| D174 | Статья затрат разносится по строкам своего счёта, ОС — нет; Ctrl+V — во все выделенные | принято (уточняет D173) | [D174-cost-item-spread.md](D174-cost-item-spread.md) |
| D175 | «Проверка книги»: программа сверяет свои данные, как Verify Data в QuickBooks | принято (опирается на D101, D149, D155) | [D175-books-verification.md](D175-books-verification.md) |
| D176 | Каждый UPDATE и DELETE называет компанию: правило под тестом, как клиент в SAP | принято (уточняет D71, D72) | [D176-company-in-every-write.md](D176-company-in-every-write.md) |
| D177 | Колонки отчёта: порядок и ширина мышью запоминаются | принято (дополняет D116) | [D177-column-memory.md](D177-column-memory.md) |
| D178 | «Журнал действий»: кто открывал компанию и что делал | принято (шаг 1 из `BACKLOG.md`; дополняет D82, D96) | [D178-action-log.md](D178-action-log.md) |
| D179 | Стек не меняется: Python, SQLite-файл, PySide6; ядро не знает о Qt | принято (опирается на D9, D18, D77, D111, D122) | [D179-stack-fixed.md](D179-stack-fixed.md) |
| D180 | «Проверено» у банковской операции | принято | [D180-bank-checked.md](D180-bank-checked.md) |
| D181 | Проводки документа модуля видны до проведения и из списков (F7) | принято (опирается на D72, D75, D90, D117) | [D181-posting-preview.md](D181-posting-preview.md) |
| D182 | Встроенный AI-чат — каждый подключает свою модель (на будущее) | принято (уточняет D83, шаг 4) | [D182-ai-chat-own-model.md](D182-ai-chat-own-model.md) |
| D183 | Счёт с проводками становится группой: «Разделить счёт» | принято (опирается на D5, D21, D22, D62) | [D183-split-account.md](D183-split-account.md) |
| D184 | Невыясненные поступления и списания (76.9) | принято (опирается на D47, D78, D146, D180) | [D184-unidentified.md](D184-unidentified.md) |
| D185 | Один счёт расчётов: авансы на 60/62; ƏDV покупок раскладывает деньги без номера сам | принято (меняет D78 для новых компаний; уточняет D138, D144, D145) | [D185-one-settlement-account.md](D185-one-settlement-account.md) |
| D186 | Строка банка не исчезает молча | принято (уточняет D37, D78, D146, D180) | [D186-bank-visible-gaps.md](D186-bank-visible-gaps.md) |
| D187 | Ручная строка банка узнаётся при загрузке файла | принято (уточняет D146, D186) | [D187-bank-hand-typed-links.md](D187-bank-hand-typed-links.md) |
| D188 | Колонки ОПиУ по субконто, строки под группами плана, процент от выручки | принято | [D188-statement-columns-by-subconto.md](D188-statement-columns-by-subconto.md) |
| D189 | Релиз и обновления: версия в одном месте, установщик, тег собирает | принято | [D189-release-updates.md](D189-release-updates.md) |
| D190 | ОСВ по месту: развороты, сортировка, одна колонка, точность, сохранённые виды | принято | [D190-interactive-osv.md](D190-interactive-osv.md) |
| D191 | Обновление из программы: спросить GitHub при запуске и раз в час, тихая установка | принято | [D191-updates.md](D191-updates.md) |
| D192 | «Доход за» в продаже: доход прошлого месяца по поздней e-qaimə — через счёт 76G «Начисленные доходы» | принято | [D192-income-month.md](D192-income-month.md) |
| D193 | «Проводки для Excel»: плоская таблица для сводной, без отчётов в программе | заменено D195 | [D193-flat-excel-postings.md](D193-flat-excel-postings.md) |
| D194 | Справочник объектов или категорий: признак справочника, не список в коде | принято (уточняет D173, D174) | [D194-directory-objects.md](D194-directory-objects.md) |
| D195 | «Проводки для Excel» убран; отчёты — окна с фильтрами по модулям | принято | [D195-remove-flat-postings.md](D195-remove-flat-postings.md) |
