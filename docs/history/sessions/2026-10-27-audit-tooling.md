# 2026-10-27, ветка claude/audit-tooling (D-new — инструменты)

Внедрение аудита инструментов; общие документы не правились — решение и «Долг» при слиянии.

- **CI**: матрица ubuntu + windows, `.python-version` 3.12, `setup-uv` с кэшем, `-n auto
  --durations=10`; на ubuntu `hledger` из apt — `test_plaintext` не пропускается (проверено
  локально); `dependabot.yml` — `uv` и `github-actions` еженедельно.
- **Медленный тест** `test_schema_rebuild.py::test_rebuilt_tables_keep_every_row`: 114 с → 3 с —
  копия строк в файл шла в autocommit (коммит и sync на строку), теперь одна транзакция.
  `test_document_language` (5–8 с) и `test_rebuild` (5,5 с) строят демо-год — дешёвого
  ускорения нет; marker `slow` не понадобился.
- **Покрытие** (`pytest-cov`): факт — **90 %** `src/modern_gl` (33 452 строки, 3 289 не
  выполнены, 1 478 тестов); `fail_under = 87`; на ubuntu в CI — artifact `coverage.xml`.
- **Hypothesis**: `test_money_properties.py` (`round_ratio` = точная дробь, половина от нуля,
  round-trip `to_minor`/`format_minor`, float отвергается, `portal_minor`) и
  `test_amounts_properties.py` (`allocate_minor`: сумма долей = итог, доли ≥ 0, пол/потолок
  точной доли, равные веса ±1; `split_charges` сходится по расходам и целям; `vat_of`,
  `unit_price`, `line_amount`). Профиль в `conftest.py`: 200 примеров, без deadline.
- **Снимки** (`syrupy`): `test_report_snapshots.py` — ОСВ, карточка, анализ, баланс, ОПиУ,
  hledger-журнал на золотом примере; ОСВ февраля 2026 сверена с докстрингом conftest.
- **pre-commit** (`.pre-commit-config.yaml`: ruff, `uv run pyright`), **релиз**: `CHANGELOG.md`,
  `release.yml` на тег `v*` → PyInstaller на Windows → zip в Release; `packaging/modern-gl.spec`
  собран и запущен на Linux (`--demo` offscreen) — нужен `collect_submodules("modern_gl")`,
  переводы ищутся через `pkgutil`. **requirements.txt** — `uv export`, `test_requirements.py`.

Dev-зависимости (п. 4.7): `pytest-cov` — покрытие числом и порогом; `hypothesis` — инварианты
на случайных входах, ручных примеров мало; `syrupy` — изменение отчёта видно в diff снимка;
`pyinstaller` — зрелый способ собрать PySide6 для Windows без установки Python.
Не удалось: сборку на Windows проверить только в CI (локально Linux).

**D-new:** | D-new | **Инструменты: coverage, hypothesis, syrupy, pre-commit, pyinstaller,
CI-матрица** (ветка `claude/audit-tooling`). CI — ubuntu и windows, Python 3.12
(`.python-version`), кэш uv, `hledger` на ubuntu, dependabot еженедельно. Покрытие `src`
измеряется на ubuntu, порог `fail_under` в `pyproject` = факт − 3 (87 при 90), поднимать вместе
с фактом. Свойства денег и распределений — `hypothesis` (`test_*_properties.py`, профиль в
`conftest.py`); отчёты на золотом примере — снимки `syrupy` в `tests/__snapshots__/` (изменение
цифр принимается `--snapshot-update` осознанно). Те же проверки перед коммитом —
`.pre-commit-config.yaml` (по желанию). Релиз — тег `v*` → `release.yml` собирает
`packaging/modern-gl.spec` на Windows, zip в GitHub Release; изменения — `CHANGELOG.md`.
`requirements.txt` только из `uv.lock` (`uv export`), тест сверяет. Dev-зависимости:
`pytest-cov`, `hypothesis`, `syrupy`, `pyinstaller`. |

Проверено: `pytest -n auto` (1 480 тестов, 3,5 мин, зелёный), `ruff`, `pyright`, `test_docs_size`.
