# Карта кода

Для автора и агентов: где что лежит и куда смотреть при типовых правках. Подробности устройства данных —
`docs/ARCHITECTURE.md`, процесс разработки — `docs/DEVELOPMENT.md`.

## Как устроено

```
реестры CSV в папке дела (registry/*.csv, case.json, journal.jsonl, sources/)
        │  store.py — Case: чтение, проверка схемы, блокировка, транзакции, журнал
        ├──► audit.py, status.py, workflow.py — проверка, состояние, следующий шаг, задачи, ревью
        ├──► exchange.py, gedcom.py, index.py — экспорт/импорт, резервная копия, GEDCOM, поиск
        └──► publish.py — публикационный набор (кто скрыт, проверка утечек)
                 └──► tree_data.py → tree.json ──► site.py + web/index.html — сайт-схема
команда kin: kin.py → cli.py (+ cli_workflow, cli_exchange, cli_services) → функции модулей выше
MCP-сервер: mcp_server.py → тот же kin отдельным процессом (белый список команд)
```

Главное правило: **источник истины — только реестры CSV**. Всё остальное (`publish/`, `site/`, `.kin/index.sqlite`)
производное и пересобирается.

## Модули `skills/kinship-kit/kin/`

| Модуль | Строк | Что делает |
|---|---|---|
| `store.py` | 430 | `Case`: реестры, ID, проверка полей по `schema.json`, блокировка `.kin/write.lock`, `transaction()`, журнал. Начинать чтение отсюда |
| `schema.json` | — | Схема реестров: поля, словари значений, префиксы ID. Старые версии — `schemas/v<N>.json` |
| `migrations.py` | 130 | `kin migrate`: перевод дела со схемы N на N+1 с резервной копией |
| `edtf.py` | 100 | Неполные даты (`1885`, `1855~`, `1890/1905`) |
| `audit.py` | 260 | `kin audit`: правила по разделам 1–8 (схема, источники, слияния, утверждения, противоречия, связи, упоминания, гипотезы и задачи, ревью) и эвристики согласованности (`_consistency`, раздел 5а) |
| `status.py` | 130 | `kin status`: состояние исследования из данных |
| `workflow.py` | 540 | Задачи (`TRANSITIONS`, `task_gate`, `rank_tasks`), гипотезы, защита от повторных поисков (`guard_search`), ревью (`checklist`, `submit_review`, `review_ok`), `next_summary` |
| `publish.py` | 320 | Кто виден (`person_visible`), публикационный набор (`build`), слова-запреты (`forbidden_terms`), проверка и замена утечек |
| `tree_data.py` | 380 | `tree.json` для страницы: колена, семьи, линии, уровни доказанности, файлы документов |
| `site.py` | 240 | `kin site build/serve`: сборка, перевод страницы, иконки, повторная проверка утечек, проверка раскладки |
| `web/index.html` | 1270 | Сама страница-схема (HTML+CSS+JS одним файлом). `web/i18n-en.json` — английские подписи, `web/check_layout.js` — проверка раскладки в node |
| `exchange.py` | 270 | Собственный экспорт/импорт без потерь, `backup`/`restore` |
| `gedcom.py` | 520 | GEDCOM 5.5.1 экспорт/импорт |
| `index.py` | 110 | SQLite-индекс и `kin find` |
| `feedback.py` | 245 | Форма «сведения семьи»: служба, черновики, решение исследователя |
| `downloaders.py` | 180 | Сборка скрипта-скачивателя (ядро + адаптер) и импорт выгрузки |
| `updates.py` | 130 | `kin upgrade check/apply` по меткам `vX.Y.Z` на GitHub |
| `mcp_server.py` | 225 | MCP (stdio), белый список `ALLOWED`, ограничения путей |
| `i18n.py` | 135 | Подписи CLI на английском: `t()` — точное совпадение по `PHRASES` |
| `cli.py` | 770 | Парсер (`build_parser`) и основные команды: источники, люди, утверждения, `add/update/show/list`, `audit`, `publish`, `site`, `doctor` |
| `cli_workflow.py` | 645 | Команды процесса: `setup`, `migrate`, `next`, `history`, `task`, `hypothesis`, `search`, `review`, `request`, `agents`, `site publish/theme`, `hooks` |
| `cli_exchange.py` | 155 | `export/import`, `backup/restore`, `gedcom`, `downloader`, `source import-download` |
| `cli_services.py` | 115 | `index/find`, `mcp`, `feedback`, `upgrade` |

Рядом с пакетом (`skills/kinship-kit/`): `SKILL.md` — методика для агента; `references/` — справочники по архивам
и правилам; `roles/` — роли агентов; `templates/tasks/` — шаблоны заданий; `downloaders/` — ядро и адаптеры
скачивателей; `kin.py` — запуск без установки.

## Типовые правки — куда смотреть

**Добавить или изменить поле реестра.** `schema.json` → новая версия схемы и миграция (рецепт — `docs/DEVELOPMENT.md`,
«Изменение схемы данных»). Если поле вводится с командной строки — карта ключей в `cli.py` (`*_MAP`, `_opts`).

**Новое правило аудита.** `audit.py`, функция `run`: выбрать раздел по номеру в комментарии, добавить в `errors`
или `warnings`. Тест — `tests/test_core.py`.

**Новая команда `kin`.** Парсер — в `add_commands` подходящего `cli_*.py` (или `build_parser` в `cli.py`),
логика — в доменном модуле, не в CLI. Через MCP новая команда **закрыта**, пока её не добавить в `ALLOWED`
(`mcp_server.py`) — добавлять, только если она пишет внутрь дела. Подписи через `t()` — с переводом в `i18n.py`.

**Вид сайта.** `web/index.html`. Поменяли русскую подпись — обновите пару в `web/i18n-en.json`
(тест `TestSiteLanguages`). Свои правки дела без изменения набора — `kin site theme` (`theme/custom.css` или
своя копия страницы).

**Что попадает на сайт.** `tree_data.py` (поля `tree.json`) — но только из того, что пропустил `publish.py`.

**Кто скрыт и что считается утечкой.** `publish.py`: `person_visible`, `forbidden_terms`, `check_leaks_text`.
Сборка сайта проверяет утечки ещё раз по всем файлам (`site.build`) и при находке удаляет сборку.

**Порядок `kin next`, правила задач.** `workflow.py`: `rank_tasks`, `task_gate` (согласие, лимит попыток), `TRANSITIONS`.

**Когда нужно ревью и что в чек-листе.** `workflow.py`: `requires_review`, `checklist`, `review_ok`; правила — `docs/REVIEW.md`.

**Новый архив для скачивателя.** `skills/kinship-kit/downloaders/adapters/<id>.js` по образцу соседних;
методика — `references/downloaders.md`; тест сборки — `tests/test_downloaders.py` (проверяет все адаптеры).

**Роль агента или шаблон задания.** `roles/*.md`, `templates/tasks/*.md`; раскладка — `kin agents install`.

**Справочник по архивам региона.** `references/*.md` — без изменений кода.

**Выпуск версии.** Версия в трёх местах: `kin/__init__.py`, `SKILL.md`, `pyproject.toml` (сверяет тест);
запись в `CHANGELOG.md`; `sh tools/check.sh` (смотреть код выхода); метка `vX.Y.Z`. Опубликованные метки не переносить.

## Тесты `tests/`

| Файл | Что проверяет |
|---|---|
| `helpers.py` | Общее: `run` (kin отдельным процессом), `Base` (временное дело), демо-дело |
| `test_core.py` | Даты, хранилище, доказательность, публикация и приватность, блокировка и откат, `doctor`, демо |
| `test_workflow.py` | `setup`, миграции, задачи и `next`, повторные поиски, ревью, решения человека, публикация сайта |
| `test_exchange.py` | Экспорт/импорт, резервная копия, GEDCOM |
| `test_site.py` | Выбор публикации, `tree.json`, документы, иконки, языки, раскладка |
| `test_services.py` | Поиск, MCP (белый список), сведения семьи, обновления, переводы подписей, Python 3.10 |
| `test_downloaders.py` | Сборка всех адаптеров, ядро в настоящем браузере (Chrome через node, если есть) |

Большинство тестов запускает `kin` отдельным процессом — так проверяется то же, что видит пользователь.

## Неочевидное

- `kin.py` лежит рядом с пакетом `kin/` — поэтому версия в `pyproject.toml` записана явно, а установка — только `pipx install -e`.
- Перевод CLI и страницы — по **точному** совпадению русской строки; за полнотой следят тесты `TestTranslations` и `TestSiteLanguages`.
- Реестры меняются только через `Case` (блокировка + журнал). Ручная правка CSV обходит журнал — аудит это заметит не всегда.
- ID последовательные: дело на нескольких машинах — пишет один клон за раз (`docs/ARCHITECTURE.md`, раздел 7).
- `ruff` закреплён на версии в `.github/workflows/check.yml`; обновлять осознанно.
- `tools/check_repo.py` и личный стоп-лист (`~/.config/kinship-kit/denylist.txt`) не дают реальным фамилиям попасть в набор.
