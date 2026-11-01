# kinship-kit — ИИ-исследование родословной

Набор для доказательного генеалогического исследования с ИИ-агентом (Claude Code, Codex):
**навык** (методика) + **CLI `kin`** (вся работа с делом) + **сайт-схема рода** (локально или для публикации).
Данные семьи хранятся в отдельной приватной папке — на вашем компьютере или сервере.

English: [README.en.md](README.en.md)

## Установка

```bash
git clone <адрес репозитория> kinship-kit && cd kinship-kit
sh install.sh            # навык в ~/.claude/skills (Claude Code) и ~/.agents/skills (Codex) + команда kin
```
Только Python 3.10+, без зависимостей. Варианты: `--claude`, `--codex`, `--project <папка>`, `--link`.

## Первый шаг

```bash
kin setup
```
Мастер спросит: **основную фамилию** (линия поиска), **название и папку дела**, **автора коммитов** в истории дела
(можно псевдоним — глобальные настройки git без вашего выбора не используются), язык и для каких ИИ-клиентов разложить роли агентов.
Для ИИ-агента то же без вопросов: `kin setup --yes --surname … --title … --author-name … --author-email …` (или `--anonymous-author`).
Фамилия добавляется в личный стоп-лист `~/.config/kinship-kit/denylist.txt` — проверка репозитория набора не даст ей уйти в публичный код.

Или просто попросите агента: «Используй навык kinship-kit, начнём исследование семьи …» — он сначала задаст эти вопросы.

## Работа

```bash
cd ~/kinship-cases/<фамилия>
kin status && kin next                      # где мы и что делать дальше (с причинами)
kin task new metric-books --goal "Рождение Ивана ≈1855" --hypothesis H-0001
kin task start T-0001 --as "Archive Researcher"
kin search add --task T-0001 --source "ГА…, ф. 15, оп. 2" --query "Иван, сын Кузьмы" --period 1853/1857 \
    --result not-found --disallowed "не значит, что не родился" --repeat-when "найдутся дубликаты"
kin source add scan.jpg --title "МК 1885, рожд. № 12" --kind document-image --repository "ГА…" \
    --ref "ф. 15, оп. 2, д. 41, л. 7" --group mk-1885-12 --provenance "ЭЧЗ архива"
kin review request H-0001                   # проверяет другая роль: Evidence Reviewer
kin audit && kin site serve                 # схема рода: http://127.0.0.1:8080
```

Пример на вымышленной семье:
```bash
python3 examples/demo/build_demo.py ~/kinship-cases/demo && kin --case ~/kinship-cases/demo next
```

## Что внутри

| Часть | Где |
|---|---|
| Навык (SKILL.md, справочники) | `skills/kinship-kit/` |
| CLI `kin` | `skills/kinship-kit/kin/` (запуск без установки: `python3 skills/kinship-kit/kin.py`) |
| Схема данных | `skills/kinship-kit/kin/schema.json`, `kin schema` |
| Роли агентов | `skills/kinship-kit/roles/` → `kin agents install` |
| Шаблоны заданий | `skills/kinship-kit/templates/tasks/` → `kin task new <тип>` |
| Архитектура хранения | `docs/ARCHITECTURE.md`, решения — `docs/adr/` |
| Независимое ревью | `docs/REVIEW.md` |
| Выкладка сайта (Caddy, GitHub Pages), форма «сведения семьи» | `docs/deploy.md` |
| Экспорт, резервная копия, восстановление | `docs/EXPORT.md` |
| GEDCOM: что переносится | `docs/GEDCOM.md` |
| MCP-сервер (Claude Desktop, Codex …) | `docs/MCP.md` |
| English | `README.en.md`, `skills/kinship-kit/references/guide.en.md`, `examples/demo/build_demo_en.py` |
| Дорожная карта и статус приёмки | `docs/ROADMAP.md`, `docs/ACCEPTANCE.md` |
| Демо-дело | `examples/demo/` |
| Проверки | `sh tools/check.sh` |

## Принципы

- Документ — это артефакт, а не факт; каждый вывод прослеживается до источника.
- Копии и индексы одной записи — не независимые подтверждения.
- Противоречия и отрицательные результаты сохраняются, а не теряются.
- Состояние исследования восстанавливается из данных дела (`kin status`), а не из памяти чата.
- Живые родственники не попадают в публичную сборку; сборка падает при утечке.

## Лицензия

MIT. Навык и справочники основаны на [ex-ussr-kinship-research](https://github.com/DenisSergeevitch/ex-ussr-kinship-research)
© 2026 Denis Shiryaev (MIT) — см. `NOTICE.md`.
