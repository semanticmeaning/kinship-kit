#!/bin/sh
# Все автоматические проверки набора (локально и в CI). Реальные данные дел не используются.
set -eu
cd "$(dirname "$0")/.."
echo "== синтаксис"; python3 -m compileall -q skills/kinship-kit/kin tests tools examples
echo "== схема данных"; python3 -c "import json,sys; sys.path.insert(0,'skills/kinship-kit'); from kin import store; print('схема v%s, реестров: %d' % (store.SCHEMA_VERSION, len(store.REGISTERS)))"
if command -v ruff >/dev/null 2>&1; then echo "== ruff"; ruff check skills/kinship-kit/kin tests tools examples; else echo "== ruff не установлен — статический анализ пропущен"; fi
echo "== тесты"; python3 -m unittest discover -s tests
echo "== приватность репозитория"; python3 tools/check_repo.py
