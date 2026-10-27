# Как вносить изменения

Короткий порядок работы. Правила и чек-лист новой функции — `docs/ENGINEERING.md`, размер
кода и обзоры — `docs/CODE_QUALITY.md`, рамка проекта — `docs/CONCEPT.md`; здесь только
то, что нужно для первого коммита.

## Ветка на задачу

Каждая задача (и каждая параллельная сессия, D131) — в своём worktree и ветке с первого
шага: `git worktree add .claude/worktrees/<имя> -b claude/<имя> master`. Основная папка —
только для слияния. Слияние — по одной ветке: `git merge master` → полный прогон тестов →
`git merge --ff-only` в `master`. Не пушить без просьбы владельца.

## Перед коммитом

```sh
uv run ruff check . && uv run ruff format --check .
uv run pyright                       # 0 ошибок
uv run pytest -q -n auto             # все тесты; один файл — без -n
uv run python tests/test_code_size.py   # что приблизилось к пределу
uv run python tests/test_docs_size.py   # документы в пределах
```

CI (`.github/workflows/ci.yml`) делает то же самое; в `master` — только с зелёным CI.
После изменений интерфейса — скриншоты `uv run python scripts/screenshots.py <папка>`.

## Тесты

- Любое изменение логики учёта — с тестом, в котором ожидаемые цифры **посчитаны вручную**
  (образец — `tests/conftest.py`, ОСВ за февраль 2026; `tests/test_demo_year.py`).
- Ошибка сначала воспроизводится падающим тестом, потом исправляется.
- Тесты интерфейса: модальные окна подменяются (`no_modal_dialogs`), текст вводится
  `type_text()`; `QT_QPA_PLATFORM=offscreen` в Linux без экрана.
- Архитектурные тесты (`test_architecture.py`, `test_database.py`, `test_code_size.py`,
  `test_read_only_ui.py`, `test_i18n.py`, `test_decisions.py`) должны оставаться зелёными;
  исключения в них не добавляются — сначала разделить код или записать в «Долг».

## Решение

Всё, что меняет смысл введённых данных или правило работы, — отдельное решение: файл
`docs/decisions/D-new-<slug>.md` (в тексте — `D-new`) из разделов «Статус», «Дата»,
«Контекст», «Решение» (слова пользователя), «Последствия» (где живёт в коде, какой тест).
Контекст и решение вместе — не длиннее 1 200 символов, подробности — в документ модуля.
При слиянии файл получает следующий номер `master` (`grep -rn "D-new"`), индекс
перегенерируется: `uv run python scripts/decisions_index.py`. Если решение меняет рамку —
правка `docs/CONCEPT.md` в том же коммите.

## Пределы

- Код (D70): модуль ≤ 600 строк, класс ≤ 500, функция ≤ 80, сложность ≤ 12
  (`tests/test_code_size.py`). Список `OVER_LIMIT` пуст и не пополняется: сначала разделить.
- Документы (D109): пределы в символах — `tests/test_docs_size.py`; документ выше ~85 %
  предела сокращается сейчас. Запись о сессии — свой файл `docs/history/sessions/`.

## Языки (D122)

- Код — имена, докстринги, комментарии — английский.
- Документы, решения, сообщения коммитов — русский.
- Интерфейс — `tr("русский текст")`, перевод — `i18n_az/<функция>.py`; текст, который
  программа пишет в документ, — `trd()` (язык документов компании, D152).
- Ошибки для пользователя — по-русски, через исключения домена.

## Коммит

Первая строка — по-русски, коротко, что сделано, как в `git log`: «Склад: поиск, товары
без остатка в списке» или «Правила учёта держит и сам файл… (D-new)». Дальше — пустая
строка и, если нужно, список: что изменилось, какой тест. Один коммит — одно дело; перенос
кода без изменения логики — отдельным коммитом.

## In English

One branch per task in its own worktree; before a commit run `ruff check`, `ruff format
--check`, `pyright` and `pytest -q -n auto`, all green. Any change to accounting logic comes
with a test whose expected figures were computed by hand. A change to the meaning of entered
data or to a working rule is a decision: a file `docs/decisions/D-new-<slug>.md` (status, date,
context, decision, consequences), numbered at the merge. Limits: a module ≤ 600 lines, a
class ≤ 500, a function ≤ 80. Code is English; documents, decisions and commit messages are
Russian; interface texts go through `tr()` with an Azerbaijani translation in `i18n_az/`.
