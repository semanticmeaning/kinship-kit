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

## Быстрый старт

```bash
kin init ~/kinship-cases/ivanovy --title "Ивановы"
cd ~/kinship-cases/ivanovy
kin source add scan.jpg --title "МК 1885, рожд. № 12" --kind document-image \
    --repository "ГА…" --ref "ф. 15, оп. 2, д. 41, л. 7" --group mk-1885-12 --provenance "ЭЧЗ архива"
kin person add --label "Иванов Пётр Иванович" --living deceased --status candidate
kin claim add --type birth --subject P-0001 --statement "Родился 2 марта 1885" --date 1885-03-02 \
    --sources A-0001 --status single-source
kin status          # что делать дальше
kin audit           # проверка доказательности
kin site serve      # схема рода: http://127.0.0.1:8080
```
Или просто попросите агента: «Используй навык kinship-kit, начнём исследование семьи …».

Посмотреть на готовом примере (вымышленная семья):
```bash
python3 examples/demo/build_demo.py ~/kinship-cases/demo && kin --case ~/kinship-cases/demo site serve
```

## Что внутри

| Часть | Где |
|---|---|
| Навык (SKILL.md, справочники) | `skills/kinship-kit/` |
| CLI `kin` | `skills/kinship-kit/kin/` (запуск без установки: `python3 skills/kinship-kit/kin.py`) |
| Схема данных | `skills/kinship-kit/kin/schema.json`, `kin schema` |
| Архитектура хранения | `docs/ARCHITECTURE.md`, решения — `docs/adr/` |
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
