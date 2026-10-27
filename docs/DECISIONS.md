# Принятые решения

Решения — файл на решение в `docs/decisions/` (статус, дата, контекст, решение, последствия),
индекс — `docs/decisions/README.md`, ещё не решённое — `docs/decisions/OPEN.md`. Найти `D72` —
`ls docs/decisions | grep D072`, по слову — `grep -rl слово docs/decisions`. Новое решение в
ветке — файл `docs/decisions/D-new-<slug>.md` (в тексте `D-new`); при слиянии — следующий
номер `master`, затем `uv run python scripts/decisions_index.py`.
