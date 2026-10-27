# D161 — Инструменты разработки: CI на Windows, покрытие, свойства, снимки, релиз
Статус: принято
Дата: 2026-10-27

## Контекст
CI проверял только Ubuntu, хотя программа — для Windows; покрытие не измерялось; деньги и распределения проверялись несколькими точками; релизов, тегов и CHANGELOG не было (аудит 2026-10-27).

## Решение
CI — матрица ubuntu и windows, Python 3.12 (`.python-version`), кэш uv, `hledger` на ubuntu, dependabot еженедельно. Покрытие `src` — на ubuntu, `fail_under` = факт − 3 (87 при 90), поднимать вместе с фактом. Свойства денег и распределений — `hypothesis`; отчёты на золотом примере — снимки `syrupy` (изменение цифр — осознанно `--snapshot-update`). `.pre-commit-config.yaml` — по желанию. Релиз — тег `v*` → `release.yml` собирает PyInstaller на Windows, zip в Release; изменения — `CHANGELOG.md`. `requirements.txt` — только `uv export`. Новые dev-зависимости: `pytest-cov`, `hypothesis`, `syrupy`, `pyinstaller`.

## Последствия
Код: `.github/workflows/ci.yml`, `release.yml`, `packaging/modern-gl.spec`, `pyproject.toml`. Тесты: `test_*_properties.py`, `test_report_snapshots.py`, `test_requirements.py`.
