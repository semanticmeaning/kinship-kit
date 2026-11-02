# Разработка набора

Где что лежит и куда смотреть при типовых правках — `docs/CODEMAP.md`.

## Проверки
```bash
sh tools/check.sh                      # синтаксис, схема, ruff (в CI обязателен), тесты, приватность репозитория
git config core.hooksPath .githooks    # pre-commit: tools/check_repo.py --staged
```
Личный стоп-лист (фамилии своей семьи и т. п.) — только вне репозитория: `~/.config/kinship-kit/denylist.txt` или `KIN_DENYLIST`.

## Процесс изменения
Task → Implementation → Automated Tests → Independent Review → Corrections → Integration → Documentation.
Тривиальные безопасные правки — без отдельного ревью. Изменения **модели данных, логики доказательности,
экспорта и приватности** — обязательно с независимым ревью (роль Code Reviewer / Security & Privacy Reviewer).

## Сайт-схема на двух языках
Шаблон — `skills/kinship-kit/kin/web/index.html` (русский). Английская версия собирается заменами из
`kin/web/i18n-en.json` (пары «точный фрагмент кода → английский»). Меняете подпись в шаблоне — обновите пару в словаре;
тест `TestSiteLanguages` проверяет, что все фрагменты словаря есть в шаблоне и что в английской версии нет русского.

## Версии
`kin/__init__.py` (`__version__`), `SKILL.md` (`version`) и `pyproject.toml` — одна версия (проверяется тестом). Выпуск:
запись в `CHANGELOG.md` (с пометкой, нужна ли `kin migrate`), коммит, метка `git tag vX.Y.Z`, `git push --tags`.
Изменения — в ветке через свой PR: CI запускается на PR и на `main`.
`kin upgrade check` у пользователей смотрит именно метки.

## Definition of Done
Функциональность реализована; тесты добавлены и проходят (`tools/check.sh`); документация обновлена
(`docs/ARCHITECTURE.md`, `SKILL.md`, `docs/ACCEPTANCE.md`); старые сценарии не сломаны (демо-дело строится);
совместимость данных проверена (изменение схемы → `schema_version` + миграция); пройдены нужные ревью;
приватность соблюдена (`tools/check_repo.py`, публичная сборка демо без живых).

## Роли разработки
Software Engineer, Code Reviewer, Security & Privacy Reviewer — `.claude/agents/` и `.codex/agents/` этого репозитория.
Исходники ролей — `skills/kinship-kit/roles/*.md`; после правки: `bin/kin agents install --set dev --target .`.

## Изменение схемы данных
1. Скопировать текущую `kin/schema.json` в `kin/schemas/v<N>.json`. 2. Изменить схему, `schema_version = N+1`.
3. В `kin/migrations.py` — `RENAMES[N]` (если поля переименованы) и `NOTES[N]`. 4. Тест миграции на деле vN.

## Демо-дело
```bash
python3 examples/demo/build_demo.py ~/kinship-cases/demo-vetluginy
bin/kin --case ~/kinship-cases/demo-vetluginy status
bin/kin --case ~/kinship-cases/demo-vetluginy site serve
```
Все люди, места, архивы и шифры демо вымышлены. Реальные данные в тесты и CI не попадают.
